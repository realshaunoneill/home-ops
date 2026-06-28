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

## Migration Rules

- Keep Unraid stack definitions in `portainer/endpoints/unraid/stacks/` (including migration-pending stacks).
- Migrate legacy Unraid containers by deploying from the stack definitions in this repo, validating data paths, then retiring old containers.

## Git Pull Workflow

- Portainer should pull/deploy stack config from this repository.
- Do not add metadata snapshots like `stack-meta.json`, `stack-index.yaml`, or inventory JSON.

## Renovate Scope

- Renovate should track compose files under `portainer/**/docker-compose.yml`.
- Legacy Kubernetes patterns should not be used.
