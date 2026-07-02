# CLAUDE.md — home-ops

Portainer **GitOps** repo for two Docker endpoints. Compose files under
`portainer/endpoints/*/stacks/` are the source of truth; Portainer pulls and
deploys them directly from this repo (public GitHub: `realshaunoneill/home-ops`).

## Topology

| Endpoint | Portainer ID | Host / connection | Runs |
|---|---:|---|---|
| `local`  | 3 | `unix:///var/run/docker.sock` (host IP `192.168.0.20`) | traefik, plex, tautulli, n8n, minecraft, gatus |
| `unraid` | 4 | Portainer agent on `192.168.0.10` (`tcp`, signed requests) | radarr, sonarr, bazarr, prowlarr, nzbget, transmission, wireguard, adguard |

Stack names can overlap across endpoints — **always use the endpoint path** when
editing (e.g. radarr existed on both historically). Repo layout:
`portainer/endpoints/<endpoint>/stacks/<stack>/docker-compose.yml`.

Key LAN hosts: Traefik/plex host `192.168.0.20`, unraid `192.168.0.10`,
router/gateway `192.168.0.1`, proxmox `192.168.0.200`, home-assistant
`192.168.0.245`, clawdbot `192.168.0.30`. Portainer UI on `192.168.0.20:9000`.

## Portainer specifics (learned the hard way)

- **This is Portainer EE** (Business, legacy 5-node license) on CE-labelled
  builds. `ServerEdition=EE`.
- **Relative path volumes are a Business feature** — available here, enabled
  per-stack **at create time only** (greyed on edit) under Advanced config,
  with a "Local filesystem path" (e.g. `/opt/<stack>/repo`).
- **Do NOT rely on relative-path (`./foo`) bind mounts for config that changes.**
  On redeploy Portainer makes a fresh checkout dir but the running container
  stays bound to the old path → dangling/empty mount → broken until a manual
  `docker restart`. Bit us repeatedly on Traefik.
- **Preferred pattern for git-driven config files: inline `configs:` blocks** in
  the compose file, mounted to the target path. Self-contained, survives
  redeploys, needs no Portainer feature. Traefik and (previously) Gatus use this.
  - Gotcha: Compose interpolates `${...}` in `configs.content`, so literal `$`
    must be doubled to `$$` (see the plex regex in the traefik compose).
- Host-path volumes (`/opt/...`, `/mnt/user/...`) are fine anywhere and need no
  special setting — most stacks only use these.
- **"Pull and redeploy"** applies compose/inline-config changes. Static Traefik
  `command:` changes also need a redeploy. `docker restart` alone can DROP the
  Portainer-injected env (see secrets) unless the value is stored on the stack.

## GitOps updates

11 stacks have GitOps polling (5m) enabled: bazarr, gatus, n8n, nzbget,
prowlarr, radarr, sonarr, tautulli, traefik, transmission, wireguard.
**plex is intentionally excluded.** minecraft is not git-backed. A push to
`master` auto-deploys within ~5 min (compose changes only — "Re-pull image" is
off, so image digests don't silently update).

## Secrets

- **Never commit secrets.** Real values go in the stack's **Environment
  variables** in Portainer (or a gitignored `.env`); compose references them as
  `${VAR}`. `.env.example` files document each.
- Externalized vars: `CF_DNS_API_TOKEN` (traefik), `POSTGRES_PASSWORD` (n8n),
  `RCON_PASSWORD` (minecraft), `PASSWORD_HASH` (wireguard/wg-easy).
- **Env-var gotchas:**
  - The Portainer env panel **interpolates `$`** — a raw bcrypt hash like
    `$2a$12$...` gets mangled. For `PASSWORD_HASH`, double every `$`:
    `$$2a$$12$$...`.
  - A stored stack env survives redeploys; a value only typed at deploy (not
    saved on the stack) is lost on redeploy/restart. Keep `CF_DNS_API_TOKEN`
    saved on the traefik stack env.
- History was scrubbed (git-filter-repo) before going public; old committed
  Cloudflare creds were verified **revoked/invalid**. `master` is clean. GitHub
  `refs/pull/*` may still hold old (dead) values — low risk.

## Traefik

- Static config lives in `traefik/docker-compose.yml` `command:`. Dynamic config
  (routers/services/middlewares) is **inline** in the same file as `configs:`
  blocks (was previously separate `dynamic/*.yml`; see
  `traefik/dynamic/README.md` for why it moved).
- File provider watches `/etc/traefik/dynamic`; Docker provider needs
  `traefik.enable=true` labels (used by n8n, tautulli — same-host only).
- **Routing model:** all routers are on the `websecure` (443) entrypoint. HTTP
  (80) globally redirects to HTTPS. Certs via Let's Encrypt **DNS-01 through
  Cloudflare** (`myresolver`, needs `CF_DNS_API_TOKEN`), stored in
  `/opt/traefik/letsencrypt/acme.json` (host path — survives redeploys).
- **File-routed hosts** (in inline config) point at fixed `host:port` backends —
  the correct pattern for services on the **other** host (unraid) or non-Docker
  targets, since the Docker provider only sees local containers. Label-based
  routing only works for containers on the same host as Traefik.
- Plex route redirects `/` → `/web/index.html#!/?bypass=1` (skips plex.tv
  discovery; note the `#` fragment may not survive an HTTP redirect in all
  browsers — VPN is the reliable fix for plex.tv-blocked networks).

## DNS & networking (important, non-obvious)

- **`*.home.shaunoneill.com` is a PUBLIC wildcard** in Cloudflare → CNAME
  `home.shaunoneill.com` → **`192.168.0.20`** (the Traefik host). So every
  internal hostname resolves from anywhere (even off-LAN) to a private IP.
  New subdomains need no DNS change — the wildcard covers them.
- Because all names share the CNAME target, Traefik's ACME DNS-01 challenge
  writes to `_acme-challenge.home.shaunoneill.com`. **Stale/orphaned
  `_acme-challenge` TXT records** (from failed attempts) cause Cloudflare error
  `81058: identical record already exists` and block ALL cert issuance until the
  stale TXT is deleted from the Cloudflare zone.
- **WireGuard (wg-easy on unraid, `network_mode: host`):**
  - Unraid bridges its NIC as **`br0`**, but wg-easy defaults its NAT masquerade
    to `eth0` — the wrong interface — so VPN→internet traffic was never NATed.
    **Fix: `WG_DEVICE=br0`** (matches the default route). Without it, tunnel
    clients can reach LAN IPs but not the internet (and DNS to public resolvers
    fails). Verify: `iptables -t nat -S POSTROUTING` shows
    `-s 10.8.0.0/24 -o br0 -j MASQUERADE`.
  - `WG_DEFAULT_DNS` only stamps **newly generated** client configs — regenerate
    a client after changing it. Set to `192.168.0.1` (router) so VPN clients
    resolve internal names via a LAN resolver rather than depending on WAN NAT.
  - Endpoint is `local.home.shaunoneill.com:51820` → WAN IP; port 51820/udp is
    forwarded. VPN subnet is `10.8.0.0/24`.
- **AdGuard Home** (unraid, `network_mode: host`, DNS :53, UI :3000): intended as
  a network-wide resolver. Can host **DNS rewrites** `*.home.shaunoneill.com →
  192.168.0.20` for clean split-horizon (internal names resolve locally, don't
  leak to public DNS). Point WireGuard `WG_DEFAULT_DNS` and/or router DHCP DNS at
  it (`192.168.0.10`) once set up. AdGuard writes its own config after the
  first-run wizard — not repo-driven; only host-path volumes are versioned.

## Version pinning / Renovate

- **Renovate GitHub App** is active (`renovate.json`) and is the primary image
  bumper. Config: automerge digest/pin/patch, group linuxserver images, hold
  majors for manual review (+`major-update` label), weekday 2-6am schedule.
- Prefer **explicit version tags** over `latest@sha256` where practical so
  Renovate proposes clean version bumps (radarr, sonarr done this way).
- **postgres is pinned to `15` — do NOT bump the major** (n8n's DB; major
  upgrades need a dump/migrate, not a tag change).
- Watchtower was removed (was unused/redundant with Renovate + GitOps).

## Conventions

- One stack per folder, `docker-compose.yml`.
- unraid stacks use `PUID=99`/`PGID=100`, `/mnt/user/...` paths, `TZ=Europe/Dublin`.
- local stacks use `/opt/...` paths.
- Keep pinned image tags for production services; timezone `Europe/Dublin`.
- No Kubernetes/Flux (legacy, removed). No metadata snapshots
  (`stack-meta.json`, inventory JSON).

## Operational access

- Diagnosing the running system is done over SSH to `realshaunoneill@192.168.0.20`
  (the local host). unraid (`192.168.0.10`) has no direct SSH key; reach its
  Docker via the Portainer API (`/api/endpoints/4/docker/...`) or the agent.
- Portainer API base: `http://localhost:9000/api` from the local host, header
  `X-API-Key: <token>`. Useful: `GET /stacks`, `PUT /stacks/{id}/git/redeploy`,
  `POST /stacks/{id}/git` (edit git settings incl. AutoUpdate).
