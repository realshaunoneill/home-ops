# Copilot Instructions for home-ops

This repository is a Portainer GitOps repo for two Docker endpoints.

## Source of Truth

- Treat compose files in `portainer/endpoints/*/stacks/` as authoritative.
- Do not reintroduce Kubernetes or Flux assets.
- Keep one stack per folder with `docker-compose.yml`.

## Environment Details

- Endpoint `local` (id 3): `unix:///var/run/docker.sock`
- Endpoint `unraid` (id 4): `tcp://192.168.0.10:9001`

Stack names may overlap across endpoints (for example, `radarr` exists on both). Always use endpoint path context when editing.

## Editing Rules

- Preserve existing bind mounts unless asked to migrate paths.
- Prefer pinned image tags for production-facing services unless the stack already uses `latest` intentionally.
- Keep timezone values unchanged per endpoint unless explicitly requested.
- Avoid changing secrets/tokens embedded in existing stack files unless requested.

## Secrets & Environment Variables

- **Never commit secret values.** Compose files reference secrets as `${VAR}`; real values live in the stack's Environment variables in Portainer (or a gitignored `.env`). Each stack that needs secrets ships an `.env.example` documenting the required names.
- Currently saved stack env vars: `CF_DNS_API_TOKEN` (traefik, stack 47), `TUNNEL_TOKEN` (cloudflared, stack 56), `POSTGRES_PASSWORD` (n8n, stack 37), `PASSWORD_HASH` (wireguard, stack 30), `RCON_PASSWORD` (minecraft, stack 15).
- **Portainer API `PUT /api/stacks/{id}/git/redeploy` wipes the stored stack env unless the request body re-supplies it.** Always GET the stack first, capture its `Env` array, and include the same array in the redeploy PUT payload. The UI's "Pull and redeploy" button preserves env; the API does not.
- The Portainer env panel interpolates `$`. Any value containing a literal `$` (bcrypt hashes, tokens with `$` characters) must have every `$` doubled to `$$` when entered.

## Cloudflare Tunnel

- Stack `cloudflared` on the local endpoint uses **token mode** — public hostnames and Access policies are configured in the Cloudflare Zero Trust dashboard, not in this repo. Only `TUNNEL_TOKEN` lives in the stack env.
- Container name is `cloudflared-home` (the host has an unrelated `cloudflared` container from a different personal project).
- On the `proxy` external network so tunnel ingress can route to Docker service names (e.g. `http://overseerr:5055`).

## Migration Rules

- Keep Unraid stack definitions in `portainer/endpoints/unraid/stacks/` (including migration-pending stacks).
- Migrate legacy Unraid containers by deploying from the stack definitions in this repo, validating data paths, then retiring old containers.

## Git Pull Workflow

- Portainer should pull/deploy stack config from this repository.
- Do not add metadata snapshots like `stack-meta.json`, `stack-index.yaml`, or inventory JSON.

## Renovate Scope

- Renovate should track compose files under `portainer/**/docker-compose.yml`.
- Legacy Kubernetes patterns should not be used.
