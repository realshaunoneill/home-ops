# CLAUDE.md — home-ops

Portainer **GitOps** repo for two Docker endpoints. Compose files under
`portainer/endpoints/*/stacks/` are the source of truth; Portainer pulls and
deploys them directly from this repo (public GitHub: `realshaunoneill/home-ops`).

## Topology

| Endpoint | Portainer ID | Host / connection | Runs |
|---|---:|---|---|
| `local`  | 3 | `unix:///var/run/docker.sock` (host IP `192.168.0.20`) | traefik, plex, tautulli, n8n, minecraft, gatus, adguard, grafana, overseerr, cloudflared |
| `unraid` | 4 | Portainer agent on `192.168.0.10` (`tcp`, signed requests) | radarr, sonarr, bazarr, prowlarr, nzbget, transmission, wireguard |

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
  - Gotcha: Portainer "Pull and redeploy" (and the git-redeploy API, even with
    `forceUpdate`) may NOT recreate the container when only inline `configs:`
    content changed — it updates the checkout but leaves the old container. If a
    config change doesn't take effect, force it on the host:
    `cd <checkout>/.../traefik && CF_DNS_API_TOKEN=<tok> docker compose -p traefik up -d --force-recreate`.
  - **Never use the container-level "Recreate" button on a compose-managed
    container.** Portainer rebuilds it from the container's *inspect* spec, which
    has no notion of compose `configs:`, so the inline mounts are silently
    dropped. Traefik came back with only its two real bind mounts and no
    `/etc/traefik/dynamic` at all, which killed **every** router: file routers
    had no config, and the docker-label routers failed resolving
    `default-chain@file`. TLS kept working off the wildcard default cert, so the
    signature is a uniform **404 on every hostname with a valid certificate** —
    it looks like a routing bug, not a missing mount. Check
    `docker inspect traefik --format '{{range .Mounts}}{{.Destination}} {{end}}'`;
    if `/etc/traefik/dynamic` is absent, that's this. Fix by redeploying the
    *stack* (which re-runs the unpacker and restores the configs), not the
    container. Portainer logs the culprit as
    `handler/docker/containers/recreate.go`.
- Host-path volumes (`/opt/...`, `/mnt/user/...`) are fine anywhere and need no
  special setting — most stacks only use these.
- **"Pull and redeploy"** applies compose/inline-config changes. Static Traefik
  `command:` changes also need a redeploy. `docker restart` alone can DROP the
  Portainer-injected env (see secrets) unless the value is stored on the stack.

## GitOps updates

11 stacks have GitOps polling (5m) enabled: bazarr, gatus, n8n, nzbget,
prowlarr, radarr, sonarr, tautulli, traefik, transmission, wireguard.
Later additions with GitOps enabled: overseerr, cloudflared.
**plex is intentionally excluded.** minecraft is not git-backed. A push to
`master` auto-deploys within ~5 min (compose changes only — "Re-pull image" is
off, so image digests don't silently update).

- **Never enable "Force redeployment" (`autoUpdate.forceUpdate`) on a stack.**
  It recreates the container on *every* poll even when the commit hasn't
  changed. Traefik had it on and was being recreated every 5 minutes,
  ~12s of downtime each time — a ~4% request-drop rate (measured 6/150
  probes failing, 0/150 after disabling) that looked like random network
  flakiness. It also aborted in-flight ACME issuance, so new certs could
  never finish. It was almost certainly switched on to work around the
  "inline `configs:` changes don't recreate the container" gotcha below —
  use the one-off `--force-recreate` there instead of leaving it armed.
  `AutoUpdate` is a **top-level** field on the stack object, NOT inside
  `GitConfig` (where it reads as `null` — easy to misdiagnose):
  ```
  curl -sS -H "X-API-Key: $PORTAINER_TOKEN" http://192.168.0.20:9000/api/stacks \
    | jq -r '.[] | select(.AutoUpdate.ForceUpdate) | "\(.Id) \(.Name)"'
  ```
  To change it, `POST /api/stacks/{id}/git?endpointId=N` with
  `autoUpdate.forceUpdate=false` — and re-supply `env` in the same body
  (same wipe caveat as the redeploy API, below).

## Secrets

- **Never commit secrets.** Real values go in the stack's **Environment
  variables** in Portainer (or a gitignored `.env`); compose references them as
  `${VAR}`. `.env.example` files document each.
- Externalized vars: `CF_DNS_API_TOKEN` (traefik), `POSTGRES_PASSWORD` (n8n),
  `RCON_PASSWORD` (minecraft), `PASSWORD_HASH` (wireguard/wg-easy),
  `TUNNEL_TOKEN` (cloudflared).
- **Env-var gotchas:**
  - The Portainer env panel **interpolates `$`** — a raw bcrypt hash like
    `$2a$12$...` gets mangled. For `PASSWORD_HASH`, double every `$`:
    `$$2a$$12$$...`.
  - A stored stack env survives redeploys; a value only typed at deploy (not
    saved on the stack) is lost on redeploy/restart. Keep `CF_DNS_API_TOKEN`
    saved on the traefik stack env.
  - **Portainer API `PUT /api/stacks/{id}/git/redeploy` WIPES the stored stack
    env** unless the request body re-supplies it as
    `env: [{name, value}, ...]`. The UI "Pull and redeploy" button preserves
    env; the API does not. Symptom: after an API redeploy, containers come up
    with empty `${VAR}` values (`CLOUDFLARE_DNS_API_TOKEN` missing on Traefik,
    tunnel connector unauthenticated on cloudflared, etc.). Fix: GET the
    stack's `Env` first, then include the same array in the redeploy PUT.
    Saved env vars currently in play: `CF_DNS_API_TOKEN` (traefik, stack 47),
    `TUNNEL_TOKEN` (cloudflared, stack 56), `POSTGRES_PASSWORD` (n8n, stack
    37), `PASSWORD_HASH` (wireguard, stack 30).
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
- **`sniStrict` must stay `false`, and the default TLS store must keep its
  wildcard cert.** With `sniStrict: true` and no default cert, Traefik aborts
  the TLS *handshake* for any SNI lacking an issued cert — a silent drop with
  no status code, no access-log line and no metric. Requests by IP died
  outright and **a newly added subdomain was dead until its cert existed**
  (invisible: every Gatus check uses a name that already has one). The
  `tls.stores.default.defaultGeneratedCert` wildcard (`*.home.shaunoneill.com`)
  now covers unmatched names, so they get a valid cert and a visible 404.
  Kept wildcard-only (no apex in `sans`) on purpose — both names authorize
  against the same `_acme-challenge.home.shaunoneill.com` record, which is
  the duplicate-TXT collision described under DNS below.
- **`websecure` sets `respondingTimeouts.readTimeout=600s`.** Traefik's default
  is 60s and it bounds reading the *entire request including body*, so any
  upload slower than that was killed mid-body with no status code. Verified by
  drip-feeding a POST: 45s body OK, 61s body dropped at t=61s; 95s body passes
  now. Matters for immich/paperless uploads from phones or over WireGuard.
- **`default-chain` must actually be referenced by routers.** It was defined
  and loading fine but attached to nothing, so HSTS/`frameDeny`/`nosniff`/
  `referrerPolicy` were absent everywhere — dead config that looked live.
  File routers list it under `middlewares:`; the six docker-routed stacks use
  `traefik.http.routers.<n>.middlewares=default-chain@file` (the `@file`
  suffix is required to reference across providers). plex/immich/paperless
  deliberately use `default-secure-headers` **instead** of the chain: they
  serve large already-compressed payloads over Range requests, where gzip
  wastes CPU and risks breaking seeking on 206 responses.
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
- lego's default DNS-01 pre-propagation check polls Docker's embedded resolver
  (`127.0.0.11`), which chains through AdGuard / systemd-resolved and can miss
  freshly-written TXT records — every new-host cert then times out with
  `did not return the expected TXT record` (existing certs keep working from
  ACME cache, so the problem is invisible until you add a new hostname). Fixed
  by pinning the pre-check resolvers to Cloudflare's own auth in
  `traefik/docker-compose.yml`:
  `--certificatesresolvers.myresolver.acme.dnschallenge.resolvers=1.1.1.1:53,1.0.0.1:53`.
  Do not remove that flag.
- **WireGuard (wg-easy on unraid, `network_mode: host`):**
  - Unraid bridges its NIC as **`br0`**, but wg-easy defaults its NAT masquerade
    to `eth0` — the wrong interface — so VPN→internet traffic was never NATed.
    **Fix: `WG_DEVICE=br0`** (matches the default route). Without it, tunnel
    clients can reach LAN IPs but not the internet (and DNS to public resolvers
    fails). Verify: `iptables -t nat -S POSTROUTING` shows
    `-s 10.8.0.0/24 -o br0 -j MASQUERADE`.
  - `WG_DEFAULT_DNS` only stamps **newly generated** client configs — regenerate
    a client after changing it. Set to `192.168.0.20` (AdGuard Home) so VPN
    clients get ad-blocking and resolve internal names via a LAN resolver rather
    than depending on WAN NAT.
  - Endpoint is `local.home.shaunoneill.com:51820` → WAN IP; port 51820/udp is
    forwarded. VPN subnet is `10.8.0.0/24`.
- **AdGuard Home** (LOCAL host `192.168.0.20`, `network_mode: host`, DNS :53, UI
  :3000): intended as a network-wide resolver. Runs on local, NOT unraid — the
  unraid host already had something bound to `0.0.0.0:53` (deploy failed with
  `bind: address already in use`); on local, systemd-resolved only holds the
  loopback `127.0.0.53`, so `0.0.0.0:53` is free. If AdGuard still can't bind
  :53 on local, set `DNSStubListener=no` in `/etc/systemd/resolved.conf`.
  Can host **DNS rewrites** `*.home.shaunoneill.com → 192.168.0.20` for clean
  split-horizon (internal names resolve locally, don't leak to public DNS).
  Point WireGuard `WG_DEFAULT_DNS` and/or router DHCP DNS at it (`192.168.0.20`)
  once set up. AdGuard writes its own config after the first-run wizard — not
  repo-driven; only host-path volumes are versioned.

## Cloudflare Tunnel (cloudflared)

- Stack `cloudflared` on local (id 56) runs `ghcr.io/cloudflare/cloudflared`
  as container `cloudflared-home` (the name `cloudflared` is already taken by
  an unrelated `maptoposter` project on this host).
- **Token mode** — routes and public hostnames are managed in the Cloudflare
  Zero Trust dashboard (Networks → Tunnels), NOT in this repo. Only
  `TUNNEL_TOKEN` lives in the stack env in Portainer.
- Container is on the `proxy` external network so ingress targets can use
  Docker service DNS (e.g. tunnel routes to `http://overseerr:5055`).
- **Cloudflare Access** gates external hostnames (email allowlist per app);
  configured under Zero Trust → Access → Applications. LAN routes via Traefik
  (e.g. `overseerr.home.shaunoneill.com`) **bypass** Access by design.
- Rotating the connector token: create/refresh in CF dashboard, save the new
  value on the stack's Env in Portainer, redeploy (remember: API redeploy
  needs env re-supplied).

## Version pinning / Renovate

- **Renovate GitHub App** is active (`renovate.json`) and is the **only** image
  bumper — Dependabot was removed (it existed solely for plex and would now
  duplicate Renovate's PRs). Config: automerge digest/pin/patch/**minor**, group
  linuxserver images, hold majors for manual review (+`major-update` label),
  weekday 2-6am schedule.
- **plex is the one image never auto-merged** (+`plex` label, kept out of the
  linuxserver group so it gets its own PR). Merging a plex bump only changes the
  repo — the stack has no GitOps polling, so it needs a manual "Pull and
  redeploy" in Portainer afterwards.
- **Tags with a per-build suffix need `versioning: loose`.** Renovate's default
  `docker` versioning only compares tags whose suffix (everything after the
  first `-`) is byte-identical, so `plex:1.43.3.10828-00f62d37d-ls315` and
  `sonarr:4.0.19.2979-ls316` were silently *never* offered an update — the
  changing git hash / `lsNNN` rebuild counter made every newer tag "incompatible".
  The `versioning: loose` rule in `renovate.json` now matches every
  LinuxServer image pinned to an `-lsNNN` tag (bazarr, nzbget, obsidian,
  overseerr, plex, prowlarr, sonarr, transmission) on either the `lscr.io` or
  `ghcr.io` prefix; add new ones there. **radarr is deliberately excluded** —
  it pins the plain upstream tag (`6.3.0`, same digest as
  `6.3.0.10514-ls314`), which default versioning handles correctly.
- **`versioning: loose` MUST be paired with the `allowedVersions` filter —
  never use it bare.** Loose treats any tag starting with digits as a version.
  Bare loose (2026-08-30 → 31) had Renovate offer, and a human merge:
  `sonarr 4.0.19.2979-ls322 → 5.14`, which is **Sonarr v2 on Mono 5.14 built
  in 2021** — loose read "5.14 > 4.0.19". Sonarr came up answering `NotFound`
  on `/api/v3` (v2 has no v3 API) and replaying v2 migrations. Also
  `bazarr → 438eee94-ls46` (git hash), `prowlarr → 2.6.3-nightly`,
  `nzbget → 26.3.20260827` (date stamp), `transmission → 4.1.3` (lost the ls
  build). Nothing was lost — Sonarr v2 uses `nzbdrone.db`, so the v4
  `sonarr.db` was untouched — but Sonarr was down until reverted in
  `fb9f55c`. The `allowedVersions` regex restricts candidates to real
  LinuxServer build tags; it is verified against the live tag lists, so
  **re-verify it if you add an image whose tags look different**. Failure mode
  is now benign: a non-conforming format means no updates, visible as a
  Dependency Dashboard warning, rather than a wrong-tag deploy.
- **wg-easy 14 → 15 is a migration, not a tag bump.** It was merged as a major
  on 2026-08-31 and crash-looped every start with `You are using an invalid
  Configuration for wg-easy ... migrate/from-14-to-15/`, taking the VPN down;
  reverted to `14`. It exits before reading config, so nothing was migrated.
  Do it deliberately, following upstream's 14→15 guide.
- **Every image now carries a real version tag; `latest` is gone.** The one
  exception is `plex-exporter` — `ghcr.io/jsclayton/prometheus-plex-exporter`
  publishes only `latest` and `main`, no version tags at all — so it stays
  `latest@sha256:<digest>` and Renovate keeps it current via digest updates.
- **To convert a `latest@sha256` pin to the equivalent version tag, read the
  image's own label rather than guessing** — the digest and the release tag's
  digest often differ even for the same build, because `latest` is a separate
  rebuild. Resolve the manifest → config blob and read
  `org.opencontainers.image.version` (LinuxServer also sets `build_version`).
  That is how each pin here was mapped to a behaviour-neutral version tag.
- **Watch for upstreams whose `latest` is not their newest release:**
  - `gatus` — `ghcr.io/twin/gatus:latest` is a rolling build of `main`; the
    newest *release* (v5.36.0, May 2026) lags it by months. Pinning the
    release tag is therefore a deliberate step back from unreleased commits.
  - `n8n` — the beta channel uses plain semver too (`next`/`beta` = 2.37.4
    while `latest`/`stable` = 2.36.8), so version comparison alone cannot tell
    a release from a pre-release and would auto-merge onto beta. **`followTag:
    "stable"` does not fix this — don't retry it.** Renovate fails with
    `Can't find version with tag stable for docker package n8nio/n8n` and then
    finds no updates at all, silently freezing the image (it showed up only as
    a warning on the Dependency Dashboard). n8n is therefore never
    auto-merged: check the proposed version is on the stable channel, then
    merge by hand.
  - `wg-easy` — `latest` == the bare major `14`; there is no `14.x.y` tag, so
    `14` is the finest pin available. v15 is a rewrite with a new config
    format, and lands as a reviewed major bump.
- **postgres is pinned to `15` — do NOT bump the major** (n8n's DB; major
  upgrades need a dump/migrate, not a tag change). The server refuses to start
  on a data directory written by an older major, and **n8n has GitOps
  polling**, so merging that bump auto-deploys straight into an outage.
  Renovate kept re-raising it (#186 n8n 15→18, #199 paperless 16→18), so
  `renovate.json` now disables **major** updates for `postgres` and
  `docker.io/library/postgres`; minor/patch still flow. Re-enable it alongside
  the migration, not before. immich's `ghcr.io/immich-app/postgres` is a
  separate vectorchord build with its own upgrade path and is not covered.
- Still on **floating major tags** (Renovate can only digest-bump these, not
  offer minor/patch PRs): `dd-agent:7`, paperless's `redis:7-alpine` and
  `postgres:16`, immich's `valkey:9-alpine`. Deliberate — pin them properly
  only if you want the PR traffic.
- Watchtower was removed (was unused/redundant with Renovate + GitOps).

## Conventions

- One stack per folder, `docker-compose.yml`.
- unraid stacks use `PUID=99`/`PGID=100`, `/mnt/user/...` paths, `TZ=Europe/Dublin`.
- local stacks use `/opt/...` paths.
- Keep pinned image tags for production services; timezone `Europe/Dublin`.
- No Kubernetes/Flux (legacy, removed). No metadata snapshots
  (`stack-meta.json`, inventory JSON).

## Home Assistant inventory tracking

- Household consumable inventory (toilet paper, washing-up liquid, etc.) should
  be modeled in Home Assistant entities, not in Grafana storage.
- Use `home-assistant/packages/household_essentials.yaml` as the versioned
  starter package for helpers, thresholds, low-stock sensors, and alerts.
- Use `home-assistant/dashboards/household_essentials.yaml` as the versioned
  Lovelace view with plus/minus stock controls.
- Keep Grafana as read-only visualization from Prometheus/HA metrics.

## Operational access

- Diagnosing the running system is done over SSH to `realshaunoneill@192.168.0.20`
  (the local host). unraid (`192.168.0.10`) has no direct SSH key; reach its
  Docker via the Portainer API (`/api/endpoints/4/docker/...`) or the agent.
- Portainer API base: `http://localhost:9000/api` from the local host, header
  `X-API-Key: <token>`. Useful: `GET /stacks`, `PUT /stacks/{id}/git/redeploy`,
  `POST /stacks/{id}/git` (edit git settings incl. AutoUpdate).
