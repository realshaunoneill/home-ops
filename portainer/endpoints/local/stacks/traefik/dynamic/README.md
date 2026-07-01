# Traefik Dynamic Config

This folder is mounted into the Traefik container at `/etc/traefik/dynamic` via
the `./dynamic` bind mount in the stack's `docker-compose.yml`. Traefik watches
it with `--providers.file.watch=true`, so edits are picked up live.

> **Requires relative path volumes.** This stack is deployed from git via
> Portainer. For the `./dynamic` bind mount to resolve to these files (rather
> than an empty auto-created directory), the stack must be created with
> **"Enable relative path volumes"** turned on (Advanced configuration on the
> stack create form). If that option is unavailable, embed the config inline in
> `docker-compose.yml` via `configs:` blocks instead.

## Files

- `middlewares.yml`: shared middleware definitions.
- `tls-options.yml`: shared TLS options.
- `bazarr.yml`, `homeassistant.yml`, `radarr-sonarr.yml`, `nzbget.yml`, `clawdbot.yml`, `plex.yml`, `prowlarr.yml`, `proxmox.yml`, `traefik-dashboard.yml`, `wireguard.yml`: per-host routes.

## Notes

- If a host is also defined by docker labels on a running container, Traefik
  will have multiple routers for the same rule. Keep one source of truth per
  hostname.
- Example label usage from app stacks:

```yaml
labels:
  - "traefik.http.routers.myapp.middlewares=default-chain@file"
```
