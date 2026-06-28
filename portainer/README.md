# Portainer GitOps Layout

This folder is the source of truth for Portainer-managed Docker stacks across endpoints.

## Structure

- `endpoints/local/stacks/*`: compose files currently managed on local endpoint.
- `endpoints/unraid/stacks/*`: compose files currently managed on unraid endpoint.

## Current Endpoints

- `local` (endpoint id 3)
- `unraid` (endpoint id 4)

## Git Pull Mode

Portainer is expected to pull/deploy from this repository. Keep compose files in this folder as the source of truth and avoid committing metadata snapshots.

## Migration Queue (Unraid)

These stacks are already tracked under `endpoints/unraid/stacks/` and can be cut over in this order:

1. `prowlarr`
2. `bazarr`
3. `nzbget`
4. `transmission`

This order minimizes media pipeline disruption while moving toward full stack coverage.

## Traefik Dynamic Config

The local Traefik stack reads dynamic config from:

- `endpoints/local/stacks/traefik/dynamic/`

This folder is bind-mounted to `/etc/traefik/dynamic` by the Traefik stack compose file, so middleware and TLS options can be versioned in git with the stack.
