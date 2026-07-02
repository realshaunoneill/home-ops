# Traefik Dynamic Config — now inline

> **These route files were moved inline into the Traefik stack's
> `docker-compose.yml`** as Docker `configs:` blocks (each mounted to
> `/etc/traefik/dynamic/<name>.yml`). This folder now only holds this README.

## Why inline instead of a `./dynamic` bind mount

This stack is deployed from git via Portainer. A repo-relative bind mount
(`./dynamic:/etc/traefik/dynamic`) requires Portainer's **relative path
volumes** (a Business Edition feature — available on this instance). It *works*,
but on every **redeploy** Portainer creates a fresh checkout directory and the
running container stayed bound to the **old** path — leaving `/etc/traefik/dynamic`
dangling/empty until a manual `docker restart` re-bound it. This happened
repeatedly and broke all file-provider routes (and blocked cert issuance) each
redeploy.

Embedding the config as `configs:` blocks in the compose file removes the
relative mount entirely: the content travels *inside* the compose Portainer
already delivers reliably, so redeploys are self-contained and safe.

## How to change a route

1. Edit the relevant `dyn_*` config block in `../docker-compose.yml`
   (the top-level `configs:` section).
2. Commit and push.
3. Pull & redeploy the `traefik` stack in Portainer.

## Gotcha: escaping `$`

Compose interpolates `${...}` in config content, so any literal `$` must be
doubled to `$$`. Example: the plex redirect regex backreference is written
`$${1}` (and the end-anchor `$$`) so Traefik receives `${1}` / `$`.
