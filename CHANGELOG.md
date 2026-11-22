# Changelog

## 0.1.0

- Authenticated full-viewport green ASCII wormhole portal, real file selection/drop, explicit destination grants and server-confirmed absorption animation.
- Separate administration listener for accounts, buckets/sub-buckets, upload permissions, revocable scoped agent tokens and bounded transfer activity.
- JSON agent CLI using the same chunked upload and exact-byte/SHA256 receipt contract.
- Bounded local temporary storage, UUID-prefixed non-overwriting archive names, CSRF/session authentication, login throttling and token-scope rechecks on mutations.
- Archive identity marker, unavailable-share health refusal, filesystem capability probe, temporary-part cleanup and database-commit compensation.
- Intake finalization uses per-transfer locks and copies to the archive outside SQLite writer transactions; live authority is rechecked before short, non-overwriting publication. Per-account reservation caps avoid one account consuming the global pending budget.
- Username-normalized login throttling prevents whitespace/Unicode variant bypasses; 120-second container shutdown grace and explicit intake-drain instructions.
- Separate per-account/per-surface login throttles avoid treating Relay's shared proxy address as a global login lockout.
- Non-root/read-only Linux amd64 Docker packaging, separate persistent local state/archive mounts, operator bundle, versioned image updates and documented rollback.
- Automated backend/CLI safety tests, real-browser workflows, and actual-container qualification. Live Babel Samba behavior and installed Relay integration require owner installation checks.
