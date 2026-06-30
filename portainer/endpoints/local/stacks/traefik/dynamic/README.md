# Traefik Dynamic Config

> **Moved inline.** The dynamic config files that used to live in this folder
> (`middlewares.yml`, `tls-options.yml`, and the per-host route files) are now
> embedded directly in the Traefik stack's `docker-compose.yml` as Docker
> `configs:` blocks, each mounted to `/etc/traefik/dynamic/<name>.yml`.
>
> **Why:** this stack is deployed from git via Portainer, which on this setup
> cannot enable "relative path volumes". A repo-relative bind mount
> (`./dynamic:/etc/traefik/dynamic`) therefore resolved to an *empty* directory
> on redeploy, so the file provider loaded no routes and every file-routed host
> returned 404. Inlining the config into the compose file removes the relative
> mount entirely while keeping everything versioned in git.

## How to change a route

1. Edit the relevant `dyn_*` config block in
   `../docker-compose.yml` (look for the top-level `configs:` section).
2. Commit and push.
3. Pull & redeploy the `traefik` stack in Portainer.

Traefik still runs the file provider with `--providers.file.watch=true`, so it
reloads the mounted files; the redeploy is only needed to push the new content
onto the host.

## Notes

- If a host is also defined by docker labels on a running container, Traefik
  will have multiple routers for the same rule. Keep one source of truth per
  hostname.
- `$` in config content must be escaped as `$$` in the compose file (Compose
  interpolates `${...}`). For example the plex redirect regex backreference is
  written `$${1}` so Traefik receives `${1}`.
