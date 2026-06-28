# Traefik Dynamic Config

This folder is mounted into the Traefik container at `/etc/traefik/dynamic`.

Files here are watched by Traefik via the file provider:

- `middlewares.yml`: shared middleware definitions.
- `tls-options.yml`: shared TLS options.
- `bazarr.yml`, `homeassistant.yml`, `radarr-sonarr.yml`, `nzbget.yml`, `clawdbot.yml`, `plex.yml`, `prowlarr.yml`, `proxmox.yml`, `traefik-dashboard.yml`, `wireguard.yml`: imported legacy host routes.

If a host is also defined by docker labels on a running container, Traefik will have multiple routers for the same rule. Keep only one source of truth per hostname.

Example label usage from app stacks:

```yaml
labels:
  - "traefik.http.routers.myapp.middlewares=default-chain@file"
```
