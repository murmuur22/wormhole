# Updates and rollback

Wormhole 0.1.0 uses the same operator-controlled **versioned Docker image + persistent bind mounts** pattern as the other WE services. The earlier experimental source-directory updater is not part of this release. There is no privileged updater endpoint, Docker socket in the app, automatic image pull, or service self-update.

## Update deliberately

1. Read the target release notes and schema compatibility. Record the currently running image **digest/image ID**, not only a mutable tag, using `docker compose images` and `docker inspect`. Download/verify the release artifact or pull the explicitly selected image. A supplied checksum establishes artifact integrity, not independent publisher authenticity.
2. Close intake at the outer gateway and wait for active transfers to finish before stopping. Containers have a 120-second stop grace period, but this is not a guarantee that a slow NAS copy will drain. An interrupted copy may retain a `finalizing` row and reserved quota until explicit operator reconciliation; do not retry or clear uncertain files blindly. Stop **both** surfaces: `docker compose stop portal admin`. Take a protected backup of the local state directory and operator configuration, and a coordinated NAS snapshot/backup as required. Keep the old image locally. Backup files include password/session/token hashes and must remain private.
3. Verify the Babel mount and archive marker again. Change only `WORMHOLE_IMAGE` in the operator's private `.env` to the selected version/digest. Leave all data paths, secret, archive ID and UID/GID unchanged. Do not move the database into the image or share.
4. Apply migrations only when explicitly required and documented by that release. There is no automatic migration on container startup. A schema-changing update needs its own tested rollback/data plan.
5. Recreate the containers: `docker compose up -d --no-deps --force-recreate portal admin`. Read both `/health` endpoints and require `status: ok`, the expected version/schema, and respectively `surface: portal` and `surface: admin`. Check login and a synthetic upload through the real entrypoint before announcing success.

## Rollback

Stop both surfaces, restore the previous image reference in `.env`, recreate them, and repeat both health checks plus a synthetic upload. An app-only rollback is safe only when the previous image understands the current database schema. **Do not restore an old account/upload database over newer acknowledged writes** merely to make old code boot. Retain the failed image, logs and backups; use a separately agreed recovery plan when schemas differ.

Updating the containers does not configure Relay targets/grants, Samba, DNS, certificates, mounts or firewall policy. Those remain independent operator actions.
