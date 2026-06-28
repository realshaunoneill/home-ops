# Unraid Stack Migration Queue

These compose files live in the managed stacks path and are used to migrate existing legacy Unraid containers into Portainer-managed stacks.

Migration queue:
- bazarr
- prowlarr
- transmission
- nzbget

Suggested migration flow:
1. Create or update the target stack in Portainer from this repo path.
2. Deploy with a temporary stack name if needed (for example, bazarr-gitops-test).
3. Validate mounts and data paths.
4. Remove or disable the legacy container.
5. Rename stack to the final production name.
