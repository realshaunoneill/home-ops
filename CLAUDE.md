# CLAUDE.md — home-ops

Portainer **GitOps** repo for two Docker endpoints. Compose files under
`portainer/endpoints/*/stacks/` are the source of truth; Portainer pulls and
deploys them directly from this repo (public GitHub: `realshaunoneill/home-ops`).

## Topology

| Endpoint | Portainer ID | Host / connection | Runs |
|---|---:|---|---|
| `local`  | 3 | `unix:///var/run/docker.sock` (host IP `192.168.0.20`) | traefik, plex, tautulli, n8n, minecraft, gatus, adguard, grafana, overseerr, cloudflared, homelable |
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
Later additions with GitOps enabled: overseerr, cloudflared, homelable.
**plex is intentionally excluded.** minecraft is not git-backed. A push to
`master` auto-deploys within ~5 min (compose changes only — "Re-pull image" is
off, so image digests don't silently update).

- **Never write a bare `[STATUS] < 400` condition in Gatus.** A failed probe
  reports status `0`, and `0 < 400` is **true**, so the condition passes when a
  service is completely unreachable. Until 2026-09-04 twelve of the seventeen
  endpoints had only that condition and each recorded **13-26 dead probes as
  successes** — they would not have alerted during a real outage. The three that
  did alert (plex, n8n, homelable) were the only ones carrying
  `[CERTIFICATE_EXPIRATION] > 168h`, which fails on a dead connection because
  cert validity reads `0s`. So the alerts blamed certificates for what was
  really DNS, and the "healthy" endpoints were the broken part of the setup.
  Every endpoint now leads with **`[CONNECTED] == true`**, and every https
  endpoint carries the cert condition. Verified in a throwaway v5.36.0 container
  before deploying — `[CONNECTED]` does resolve, it is not treated as a literal.
- Gatus fires **all** checks in one synchronised burst at boot, and Go queries A
  and AAAA in parallel, so ~17 endpoints means ~34 concurrent lookups. That is
  what tripped AdGuard's rate limit; the stack now sets
  `dns_opt: [single-request, timeout:2]` to serialise the pair. Failures used to
  cluster visibly — up to 11 endpoints in the same minute, which is the
  signature of a shared resolver problem rather than 11 sick services.
- Durations are the quickest way to spot this class of fault: healthy is p50
  ~23ms, and a **fat tail at exactly `10001ms` is the Gatus client timeout**,
  i.e. DNS stalling, not a slow backend.
- **Editing `gatus/config/config.yaml` needs a manual `docker restart gatus`.**
  The compose file itself doesn't change, so the 5m poll updates the git
  checkout and advances the stack's `ConfigHash` — and stops there. Gatus only
  reads its config at boot, so the new checks silently never load: the stack
  looks fully up to date at the new commit while the running container is still
  serving the old check list. Caught adding the homelable checks (stack sat at
  the new hash, `/api/v1/endpoints/statuses` still returned the old 15).
  Diagnose by comparing the two:
  ```
  curl -sS -H "X-API-Key: $PORTAINER_TOKEN" http://192.168.0.20:9000/api/stacks/46 | jq -r .GitConfig.ConfigHash
  docker inspect gatus --format '{{.State.StartedAt}}'
  ```
  A restart is the right fix and is **safe**: despite the relative-path warning
  above, the poll rewrites the config **in place** at the same checkout path
  (verified — the bound source already held the new content), so the mount is
  not dangling. `docker restart` also reuses the container spec, so the stored
  `GATUS_PUSHOVER_*` env survives; confirmed identical before and after. Do
  **not** reach for an API stack redeploy here, which would wipe that env, nor
  the container Recreate button.
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
- **`POST /api/stacks/{id}/git` CLEARS `AutoUpdate.JobID`, which silently kills
  GitOps polling for that stack.** Hit on wireguard (30) on 2026-09-04 while
  adding an env var: `Interval` still reads `5m` so the stack *looks* like it is
  polling, but the scheduler job is gone and pushes stop deploying. Re-POSTing,
  including toggling `autoUpdate` to `null` and back, does **not** re-create it.
  Compare against a healthy stack — gatus (46) has `JobID: "10"`; an empty
  string is the tell:
  ```
  curl -sS -H "X-API-Key: $PORTAINER_TOKEN" http://192.168.0.20:9000/api/stacks \
    | jq -r '.[] | "\(.Id) \(.Name) jobid=\(.AutoUpdate.JobID // "-")"'
  ```
  Fix it in the **UI** — turn GitOps updates off and on again on the stack. So
  prefer setting stack env in the UI, or re-check `JobID` afterwards if you use
  the API.

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
    `$$2a$$12$$...`. **This applies to env set over the API too**, not just the
    UI panel — verified on homelable: `AUTH_PASSWORD_HASH` was POSTed with
    doubled `$` and `docker exec homelable-backend printenv` showed a correct
    60-char, 3-`$` hash, with a login round-trip confirming it (right password
    200 + JWT, wrong password 401). So double it wherever you set it.
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
- **cevo's resolver list was broken and is now FIXED at the source
  (2026-09-04).** It used to be
  `DNS Servers: 192.168.0.10 192.168.0.5 8.8.8.8`, where **unraid (`.10`)
  actively REFUSES :53** and **`192.168.0.5` does not exist at all** (no ping,
  absent from a full LAN scan), so it black-holed. Every lookup on the box
  walked that list before reaching `8.8.8.8`. Measured from a container on this
  host: **1 failure in 20 lookups, worst case 11.9s.**
  - **The dead servers were STATIC, in `/etc/netplan/50-cloud-init.yaml`** —
    not DHCP, which is where you would look first. They were set on both
    `eth0` and `eth1`. Now `192.168.0.20` (AdGuard), `1.1.1.1`, `1.0.0.1`.
  - **A `99-*.yaml` netplan override does NOT work for this.** Netplan
    *appends* `nameservers.addresses` across files rather than replacing them,
    so the dead servers stayed at the head of the list and nothing improved.
    Verify with `grep ^DNS= /run/systemd/network/10-netplan-eth0.network`.
    The source file has to be edited.
  - `/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg` now pins that file,
    because cloud-init regenerates it on reboot and would restore the dead
    servers. Backup at `50-cloud-init.yaml.bak-dnsfix`.
  - Also removed `eth1`'s default route, which duplicated `eth0`'s and made
    `netplan generate` fail with `Conflicting default route declarations`.
    `eth1` does not exist on this VM (its `match` MAC matches nothing).
  - **This was never only a host problem — it broke every container too.**
    `/etc/resolv.conf` is the systemd-resolved stub (`127.0.0.53`), and Docker
    cannot hand a loopback address to a container, so dockerd reads
    **`/run/systemd/resolve/resolv.conf`** instead and forwards the embedded
    resolver (`127.0.0.11`) at whatever that file lists. That is generated from
    netplan, so the dead servers were the upstream for every bridge container
    on the host. Check that file, not `/etc/resolv.conf`, when container DNS
    misbehaves.
  - The failure mode is nasty because it is intermittent and blames the wrong
    thing: it took out all 20 hostname-based status checks in homelable (5s
    timeout) while `curl` from the same host succeeded every time, and it made
    Gatus flap for months (see the Gatus notes under GitOps updates).
    homelable and gatus both still pin `dns: [192.168.0.20, 1.1.1.1]` — keep
    them, they are cheap insurance against this regressing silently.
  - Verified after the fix: 17 concurrent lookups from a bridge container,
    3 cycles, **0 failures, max 9ms** (was a 15-25% failure rate with a 10s
    tail).
- **AdGuard Home** (LOCAL host `192.168.0.20`, `network_mode: host`, DNS :53, UI
  :3000): intended as a network-wide resolver. Runs on local, NOT unraid — the
  unraid host already had something bound to `0.0.0.0:53` (deploy failed with
  `bind: address already in use`); on local, systemd-resolved only holds the
  loopback `127.0.0.53`, so `0.0.0.0:53` is free. If AdGuard still can't bind
  :53 on local, set `DNSStubListener=no` in `/etc/systemd/resolved.conf`.
  AdGuard writes its own config after the first-run wizard — **not repo-driven**;
  only host-path volumes are versioned. Config lives at
  `/opt/adguard/conf/AdGuardHome.yaml`; **stop the container before editing it**,
  or it will overwrite your changes. Backups from the 2026-09-04 work:
  `AdGuardHome.yaml.bak-dnsfix` and `.bak-rewrites`.
- **Split-horizon rewrites are now ENABLED** (`*.home.shaunoneill.com` and the
  apex → `192.168.0.20`). They existed but sat at `enabled: false`, so every
  internal lookup made a WAN round trip to Quad9 over DoH. Now ~0ms and local.
  - **The wildcard shadows any name in the zone that points elsewhere.** Two do,
    both at the WAN IP: `local.home.shaunoneill.com` (the WireGuard endpoint)
    and `mc.home.shaunoneill.com` (Minecraft, port-forwarded). Both now have
    **pass-through exception rewrites**, which is `answer` set equal to the
    domain itself — that makes AdGuard resolve upstream instead of rewriting,
    so the dynamic WAN IP is not hardcoded anywhere. **Add an exception for any
    future record that is not `192.168.0.20`**, or it silently resolves to the
    wrong host. Enumerate them from Cloudflare, don't guess.
  - The wildcard also swallows `TXT` for `_acme-challenge.home.shaunoneill.com`
    (AdGuard answers empty; `1.1.1.1` returns the real record). **Harmless
    only because** Traefik pins lego to
    `--certificatesresolvers.myresolver.acme.dnschallenge.resolvers=1.1.1.1:53,1.0.0.1:53`
    and so never asks AdGuard. Do not remove that flag.
- **`ratelimit` was 20 q/s and is now 200, with `127.0.0.1` and `192.168.0.20`
  whitelisted.** The trap is `ratelimit_subnet_len_ipv4: 24`: clients are
  bucketed per /24, so the **entire LAN shared one 20 q/s allowance**, and this
  host aggregates every container's DNS through the embedded resolver. Bursty
  clients (Gatus resolves ~17 names at once) silently lost queries — AdGuard
  drops them rather than refusing, so it looks like packet loss.
- `querylog.interval` was `90d`, which had grown `querylog.json` to **1.5 GB**;
  now `7d`. Worth watching — a full disk here takes down DNS for the LAN.
- Point router DHCP DNS at `192.168.0.20` to finish the split-horizon story.

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

## Homelable

Visual homelab mapper (`github.com/Pouzor/homelable`, MIT) on **local**, three
containers from one version: `homelable-backend`, `-frontend`, `-mcp`.
`homelable.home.shaunoneill.com` (SPA, also `:3002`) and
`homelable-mcp.home.shaunoneill.com` (`:8001`). Data in `/opt/homelable/data`.

- **The backend runs `network_mode: host`, on purpose.** The scanner reads MAC
  addresses from ARP, which is layer 2 — from a bridge network every LAN host
  is one hop away behind the Docker gateway, so the MAC field stays
  permanently empty and `cap_add: NET_RAW` does not change that (it grants raw
  sockets, not a place on the LAN). Empty MACs also break device identity:
  rescans match on MAC first and IP second, so a DHCP lease change re-adds a
  device as a new inventory entry. This is why the stack is not a copy of
  upstream's compose.
- **Consequence: `backend:8000` does not resolve.** The backend binds
  `0.0.0.0:8000` on `192.168.0.20` with no port mapping. So the frontend's
  shipped nginx.conf (which proxies to `backend:8000`) is replaced wholesale
  by an inline `configs:` block pointing at `192.168.0.20:8000`, and `mcp`
  gets the same address via `BACKEND_URL`. **Change all three together.**
  The inline config also raises `client_max_body_size` to 50m — nginx's 1m
  default 413s a phone photo on a floor-plan upload.
- **Every secret is `${VAR:?...}`-guarded, so a missing value fails the deploy
  rather than starting.** Deliberate: the backend is on a LAN-exposed port
  with no Traefik in front, and the API redeploy endpoint is known to wipe
  stored stack env (see Secrets). Failing loudly beats coming up with no auth.
  `AUTH_PASSWORD_HASH` is bcrypt, so it hits the Portainer `$`-interpolation
  gotcha — store it with every `$` doubled, as with wireguard's
  `PASSWORD_HASH`.
- `CORS_ORIGINS` must list every browser origin used. A missing entry fails
  the SPA's fetches with a CORS error while the API itself looks healthy.
- Gatus checks the SPA *and* `http://192.168.0.20:8000/api/v1/health`
  separately — because of host networking a frontend 200 only proves nginx is
  up, not the API behind it.
- The MCP server speaks streamable HTTP at **`/mcp/` — the trailing slash
  matters**, `POST /mcp` answers `307` to it. Auth is the `X-API-Key` header
  (not Bearer). Verified working both on `192.168.0.20:8001` and through
  Traefik at `https://homelable-mcp.home.shaunoneill.com/mcp/`; it reports
  itself as server `homelable` and exposes tools + resources.
- **No per-host certs exist for these two names, deliberately.** Every other
  host has its own entry in `acme.json`, but Traefik saw the
  `*.home.shaunoneill.com` wildcard already covers them and skipped issuance —
  no ACME request, no error. They serve the wildcard and verify clean
  (`ssl_verify_result=0`). Nothing to fix; do not go hunting for a missing
  cert here.
- The MCP router uses `default-secure-headers@file`, not `default-chain` —
  the chain adds compress and gzip buffering breaks streamed MCP responses
  (same reasoning as plex/immich/paperless).
- Can import from Proxmox (`192.168.0.200`) and Zigbee2MQTT / Z-Wave JS over
  the HA broker (`192.168.0.245`); all off until configured, see
  `.env.example`. One-off imports pass credentials in the UI dialog, which
  keeps them out of the stack env entirely.
- There is also a HACS integration (`Pouzor/homelable-hacs`) that runs natively
  inside Home Assistant. Not used here — this is the standalone Docker stack.

## Media apps (Radarr / Sonarr / NZBGet)

None of this is repo-managed — it lives in each app's own database, so it is
only reachable over their APIs. Keys are in `.service-api-keys.local.env`
(gitignored): `RADARR_API_KEY`, `SONARR_API_KEY`, `NZBGET_USERNAME/PASSWORD`.
Both apps are usenet-only in practice: **NZBGet is the only enabled download
client** (SABnzbd is defined but disabled, and transmission is not registered
in either app at all, which is why `/plex/torrent` sits empty).

- **Fake `.exe` releases are blocked by a Release Profile in both apps
  (2026-09-04).** Sonarr grabbed six of them between 08-31 and 09-02 —
  `Reacher`, `Lioness` ×2, `Ted.Lasso`, `Its.Always.Sunny`, `The.Terminal.List`
  — all named `<release>.exe-[N-Z-B]-xpost`, all of which downloaded and then
  failed to import. Radarr had **zero** (movies get grabbed far less: 11 vs 457
  in the same month). The ignored term, on both, applies to all items
  (`tags: []`):
  ```
  /\.(exe|msi|scr|pif|lnk|vbs|vbe|jse|wsf|wsh|hta|cpl|cmd)\b/i
  ```
  - **Do NOT add `.com`, `.bat`, `.iso`, `.js` or `.ps1` to that regex.** They
    collide with real release names — validated against 3590 historical titles,
    where a broader pattern also matched
    `It.Chapter.Two.2019...6CH-MkvHub.Com-Obfuscated`. `.bat` hits real titles
    ("The Bat", "BAT*21") and `.iso` is legitimate for full-disc releases.
  - **Do NOT filter on `[N-Z-B]` or `-xpost`.** They look like the malware
    signature but are not: `Backrooms.[2026]...mkv-[N-Z-B]-xpost` imported fine.
    Key on the executable extension only.
  - **Radarr has no UI page for Release Profiles** — the feature was dropped
    from the frontend but `ReleaseProfileService` and
    `ReleaseRestrictionsSpecification` are still in `Radarr.Core.dll` and still
    enforce. So the Radarr rule is real but **invisible in the web UI**; manage
    it at `/api/v3/releaseprofile`. Sonarr shows its own under
    Settings → Profiles → Release Profiles.
  - Verify with an interactive search rather than trusting the config — a
    rejected release reports the reason:
    `Contains these ignored terms: /\.(exe|...)/i`.
- **NZBGet `ExtCleanupDisk` now also deletes executables**, as defence in depth:
  the release profiles match the *title*, so they cannot catch a clean-looking
  release that unpacks an `.exe`. `.bat` and `.com` ARE safe to include here,
  unlike in the title regex, because this matches real files on disk.
- **`saveconfig` over the NZBGet JSON-RPC API is a trap — do not use it.**
  The `config` method returns four read-only informational entries
  (`ConfigFile`, `AppBin`, `AppDir`, `Version`); handing them back to
  `saveconfig` writes them into `nzbget.conf`, where they are **not valid
  options**. On the next reload NZBGet logs `Invalid option "ConfigFile"` ×4 and
  **`Pausing all activities due to errors in configuration`** — downloads stop,
  while Radarr/Sonarr's "Test" still returns 200 and reports no health warning,
  so nothing surfaces the breakage. Edit `/config/nzbget.conf` directly instead
  (`sed` the one line, keep it `chown 99:100`) and then call `reload`. Confirm
  with `/jsonrpc/status` → `ServerPaused=false` and a clean `/jsonrpc/log`.
  Backup of the pre-change file: `/config/nzbget.conf.bak-extcleanup`.

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
- **wg-easy is now on 15 and the migration is DONE (2026-09-04).** History worth
  knowing: #208 bumped it to 15 and it crash-looped with `You are using an
  invalid Configuration for wg-easy ... migrate/from-14-to-15/`, taking the VPN
  down; `fb9f55c` reverted it. **#212 then re-merged 15**, and `9fbc238`
  refactored the compose to suit it — dropping every `WG_*` env var, because v15
  genuinely does not read them. Nothing replaced them, so the VPN sat with
  **zero configured peers for four days** while the Gatus `wireguard-ui` check
  stayed green (that check only ever proved the web UI was up, never the
  tunnel). See `wireguard/docker-compose.yml` for the full v15 notes; the two
  traps are that **`device` defaults to the literal `eth0`** (wrong on unraid,
  and settable only in the database) and that **`INIT_HOST` is silently
  ignored** while the other `INIT_*` vars work.
- **The three homelable images are grouped into one Renovate PR.** They share a
  version and a versioned API, so a solo frontend bump would leave it talking
  to an older backend; the shared `groupName` makes the bump atomic. Their tags
  are plain semver (`3.3.5`) — default `docker` versioning is correct, do
  **not** add `versioning: loose` to them.
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
