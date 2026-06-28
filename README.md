# home-ops

Portainer GitOps repository for two Docker servers.

## Servers

| Server | Endpoint Name | Endpoint ID | Connection | Notes |
|---|---|---:|---|---|
| Main host | local | 3 | unix:///var/run/docker.sock | Primary services, Traefik, media, n8n, minecraft |
| Unraid host | unraid | 4 | tcp://192.168.0.10:9001 | Media automation and VPN workloads |

## Repository Layout

- `portainer/endpoints/local/stacks/` - Stack compose files currently managed on the local endpoint.
- `portainer/endpoints/unraid/stacks/` - Stack compose files currently managed on the Unraid endpoint.

## Current Stack Coverage

Managed in Portainer now:

- local: radarr, tautulli, sonarr, plex, watchtower, traefik, minecraft, n8n
- unraid: wireguard, radarr, sonarr

Unraid stack configs already in git (pending cutover where noted):

- bazarr
- prowlarr
- nzbget
- transmission

## Git-Driven Workflow

- Portainer should pull/deploy stack definitions directly from this repo.
- Compose files in `portainer/endpoints/*/stacks/` are the source of truth.
- Metadata snapshots (`stack-meta.json`, `stack-index.yaml`, inventory JSON) are intentionally not tracked.
- No export/bootstrap helper script is required in this repo.
