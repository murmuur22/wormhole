# Wormhole

A shared media-archive intake service for people and AI agents.

- **Human portal:** sign in, pick or drop a file, choose an assigned bucket, and Toss into a full-viewport Three.js ASCII wormhole. The absorption animation completes only after a real storage receipt.
- **Separate administration surface:** create/disable archivists, configure shared buckets/sub-buckets, assign explicit upload grants, issue/revoke narrowly scoped agent tokens, and inspect recent transfer metadata.
- **Agent CLI:** list permitted buckets and upload through the same chunk/integrity/permission contract, with JSON receipts.

No public signup, default password, file execution, archive browsing/download or archive deletion endpoint is included. Upload permission does not imply those powers. The admin listener does not register upload routes; the portal listener does not register administration routes.

## 0.1.0 deployment

Use Docker on the application host, with **local** persistent state/SQLite/temporary parts and a separately mounted archive directory. For the intended Relay VM + Babel NAS setup, mount Samba on the host VM and bind only the required archive subtree into the containers. An archive identity marker and host-side mount verification prevent an absent share from becoming an accidental local archive.

- [Docker installation and Babel storage](docs/docker-install.md)
- [Operator-controlled Docker updates and rollback](docs/updating.md)
- [Relay Gateway permissions, cookies and headers](docs/relay.md)

The initial image/build targets Linux amd64. Release source, image archive and operator bundle do not install services, change Samba, register Relay targets or create access grants. Real Babel filesystem/reconnect behavior and installed Relay compatibility remain installation acceptance checks.

## Agent CLI

The operator bundle contains `wormhole-cli.py`; it requires Python 3.12+ and no third-party packages. Obtain a scoped token from the administrator, then supply `WORMHOLE_TOKEN` or a protected owner-only `--token-file`. Do not put a token in command arguments or source control.

```sh
python wormhole-cli.py --url https://your-authorized-portal.example buckets
python wormhole-cli.py --url https://your-authorized-portal.example upload recording.flac --bucket 1
```

Inside a source checkout, use `python -m wormhole.cli` instead. HTTPS is required except for loopback HTTP. Redirects and ambient HTTP proxies are refused to avoid forwarding bearer credentials elsewhere. A lost finish response is an uncertain outcome: inspect recent transfer metadata before retrying to avoid duplicate archives.

## Storage and security boundaries

Files are streamed in 512 KiB chunks into bounded local temporary storage, then checked and published without overwriting existing names. The server records original name, uploader, bucket, actual bytes, SHA256 and outcome. Stored names have a server-generated UUID prefix. Bucket grants are explicit: granting a parent does **not** automatically grant its children. Token scopes are intersected with live account grants and checked on each upload mutation. Inactive accounts, revoked grants/tokens and invalid explicit bearer headers are refused; cookie mutations retain CSRF protection.

Initial bounds: 2 GiB per file, four pending transfers/account and 2 GiB reserved pending bytes/account, 8 GiB reserved pending bytes globally, 24-hour transfer lifetime. These are intake bounds, not an unlimited archive-storage promise or lifetime quota. Account/password/session state is private; administrator access is broad and must be trusted. First-run enrollment uses Django's interactive `createsuperuser`, not an open web bootstrap.

The app/database/NAS are not one power-loss transaction. Unexpected failures may require reconciliation of unacknowledged UUID-named files. See the installation guide before accepting real media. No malware scanner or file-content viewer is included.

## Development and qualification

Python 3.12+, Node 22+, uv 0.12.10. Exact Python dependencies are locked in `uv.lock`; browser tooling is locked in `package-lock.json`. Three.js 0.180.0 is bundled locally with its MIT notice, with no CDN assets or external fonts.

```sh
uv sync --locked --python 3.12
uv run python manage.py test tests --settings=tests.settings --noinput
uv run ruff check core wormhole tests scripts manage.py
npm ci --ignore-scripts
npx playwright install --with-deps chromium
npm run test:browser
```

Tests use disposable synthetic accounts/media and real local listeners, browser requests and CLI transfers. `WORMHOLE_TEST_TMPDIR` can select a suitable scratch directory. `WORMHOLE_BROWSER_EXECUTABLE` can select an already-installed compatible Chromium. The browser runner owns and closes its fixture processes and writes screenshots/results under ignored `artifacts/`.

GitHub Actions additionally builds and runs the actual Linux Docker image with disposable mounted directories. This tests the image, persistence and missing-marker refusal, **not** a real SMB server. Versioned image publication occurs only on an explicitly pushed release tag after the qualification steps pass. There is no automatic deployment.

See [third-party notices](THIRD_PARTY_NOTICES.md). An original-code project license has not been selected.
