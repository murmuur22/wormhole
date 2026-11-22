# Docker installation and Babel storage

## Recommended topology

Run Wormhole's **portal and administration containers on the Relay VM**. Keep the account/session/upload database and temporary file parts on the VM's local filesystem. Mount a dedicated Babel SMB share on the **host VM**, then bind that existing directory into both containers at `/archive`. Do not put SQLite on SMB; do not give a container privileged mount capabilities or embed Samba credentials in its image/environment.

This keeps an authenticated upload-facing application off the NAS appliance. Running on Babel is an alternative only if Babel is deliberately also an application host with supported Docker, resource isolation and an acceptable security boundary. It is not required for this release.

**The real Babel share, SMB durability, reconnect behavior, capacity, UID/GID mapping and Relay Gateway integration must still be tested at installation.** Local directory and container tests do not qualify the NAS. Nothing in this repository changes live mounts or network infrastructure.

## Prepare the host deliberately

1. Obtain the exact NAS host/share and intended archive directory. Configure its mount using a root-owned credentials file readable only by root; follow the VM/NAS's supported SMB configuration. Use a dedicated NAS account restricted to Wormhole's archive subtree, not the entire library. Never paste passwords into Compose or command arguments.
2. Make the Samba mount a prerequisite of starting/recreating the containers, e.g. an operator-managed systemd unit with `RequiresMountsFor=` for the exact mount path. Verify `findmnt -T /mnt/babel/wormhole` shows the intended CIFS filesystem, not the VM root filesystem, before writing anything. Directory existence alone is not proof the share is mounted.
3. Create a **local** state directory such as `/srv/wormhole/state`, with ownership/mode appropriate for the unprivileged container UID/GID (defaults 10001:10001; state 0700). Map the NAS folder's ACL/mount permissions to that same identity. Do not broadly chmod/chown an existing media library.
4. Generate a private random secret of at least 32 characters and an independent 32-character lowercase hexadecimal archive ID. On the verified NAS-backed dedicated folder only, write that ID followed by one newline to `.wormhole-archive-id`. Protect the marker from modification by upload users. It is an identity marker, not a secret or a substitute for mount verification.
5. Copy `.env.example` to an operator-local `.env` (0600), replacing every placeholder. Set the actual local state/archive paths, archive ID, secret, and any UID/GID differences. Neither secrets nor `.env` belongs in Git.

The application rechecks the archive marker on beginning/finalizing uploads and in health checks. Compose refuses to auto-create absent bind-source directories. If the host mount is lost/replaced, stop the containers, recover/verify the correct mount, then recreate the containers so they bind the intended mount again. Do not clear markers or relax identity checks to get a green health check.

## Obtain and start 0.1.0

Use the release's versioned GHCR image, preferably pinned by its downloaded registry digest. The repository/package may be private, requiring explicit registry read authorization. Alternatively download and verify the Docker image archive and `SHA256SUMS` from the private GitHub release, then load it with `docker load -i wormhole-0.1.0-linux-amd64.docker.tar.gz` and set `WORMHOLE_IMAGE=wormhole:0.1.0`. The initial packaged image targets Linux amd64.

From the operator bundle directory containing `compose.yaml` and `.env`:

```sh
docker compose pull
# With no services yet running, initialize only the local database:
docker compose run --rm admin python manage.py migrate --noinput
# Create a real initial administrator interactively; no default password exists:
docker compose run --rm admin python manage.py createsuperuser
# Test the exact mounted filesystem's required operations before accepting media:
docker compose run --rm admin python manage.py check_archive
docker compose up -d
curl --fail http://127.0.0.1:8751/health
curl --fail http://127.0.0.1:8752/health
```

Skip `docker compose pull` when using an already verified, locally loaded image archive. Do not open both ports publicly. Both host bindings default to loopback; the container's own port 8000 is internal. Run cleanup periodically through an operator-configured job:

```sh
docker compose exec -T admin python manage.py cleanup_uploads
```

The cleanup command removes expired/cancelled/completed **temporary parts**, never committed archive files. No cron job is installed automatically. Default file bound is 2 GiB, chunk size 512 KiB, four pending transfers per account with a 2 GiB total per-account reservation cap, 8 GiB aggregate reserved pending bytes, and 24-hour transfer expiry. Upload permission is not archive read/delete access.

## Before accepting real media

- Through actual Babel SMB: run `check_archive`; upload a synthetic multi-chunk file, compare SHA256 and exact NAS bytes, restart containers, and recheck. Test NAS disconnect/reconnect without real media. Required storage operations include secure regular-file opens, fsync, atomic no-overwrite hard-link publication and directory fsync; unsupported SMB/server semantics must fail qualification rather than be silently weakened.
- Confirm host disk headroom for temporary parts, NAS free space and independent backups/snapshots. Chunk size bounds RAM but not total retained disk use; account grants are not a lifetime archive quota.
- Test portal/admin Relay grants separately, including ordinary-user admin denial, session expiry and revoked bucket permissions.
- The file/database commit is not a distributed, power-loss transaction with the NAS. Unexpected process/VM/NAS failure can leave an unacknowledged file or `.incoming-…` artifact. Preserve it for operator reconciliation through the upload UUID and checksum; never overwrite/delete possible archives automatically to resolve uncertainty. Interrupted finalization or a pre-existing publication path is exposed as `reconcile` in admin transfer metadata and returns a distinct 409 response; existing files are preserved. Cleanup intentionally retains `finalizing`/`reconcile` parts and reservations. Stop both surfaces, preserve a database/NAS snapshot, and reconcile the UUID, expected checksum, local part and archive file before an operator clears that state. There is no automatic destructive crash-recovery command in 0.1.0.
