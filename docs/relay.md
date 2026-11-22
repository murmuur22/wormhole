# Relay integration boundary

Register **two distinct Gateway targets/apps**, pointing at the separate portal and administration host ports. Grant the portal only to intended archivists and the admin target only to administrators. Keep the upstream host ports private. If Relay itself runs in a container, its loopback is not the VM's loopback; select a deliberate private container/host route rather than exposing both services broadly.

Relay Gateway grants are outer access control, **not SSO**. Users still authenticate to Wormhole, which enforces account activity, scoped agent tokens and bucket permissions. Never inject a trusted username header or disable Wormhole CSRF to make integration work.

For each target, explicitly configure its fixed upstream address, `httpOrigin: "upstream"`, and the relevant cookie allowlist:

- Portal: `wh_portal`, `wh_csrf_portal`.
- Administration: `wh_admin`, `wh_csrf_admin`.

Allow request header `x-csrftoken`; the portal also needs `x-chunk-sha256`. Authenticated CLI requests through a supported Relay agent transport additionally need `authorization`, with that transport qualified separately. The included CLI works directly with an explicitly authorized private/HTTPS portal origin; it does not manufacture a Relay browser-session capability.

Chunks are 512 KiB, below Relay's documented default 1 MiB per-request cap. Do not raise an app's whole-request limit to gigabytes or disable external Origin validation. Set Wormhole's exact upstream `WORMHOLE_HOSTS` to match the chosen canonical Host. `WORMHOLE_FRAME_ANCESTOR` may contain the exact HTTPS Relay desktop origin, enabling embedding through a narrowly scoped CSP; otherwise embedding is denied. Secure cookies remain on for browser-facing HTTPS. Use loopback HTTP with cookies explicitly non-Secure only for deliberate local testing, not Internet exposure.

Separate target hostnames are recommended; host cookies are not isolated by port. Login throttles are per account **and per surface**, not per shared proxy peer. Repeated attempts can temporarily throttle the targeted account for up to 15 minutes; this is a deliberate brute-force/availability tradeoff, not a global gateway lockout. Keep the admin target restricted, and add suitable edge abuse controls if opening the portal beyond the trusted community.

On first installation, prove login, CSRF, multi-chunk uploads, logout, account/bucket revocation and ordinary-user denial of the admin target through the actual installed Relay version. Reading these settings or testing direct local listeners does not establish live Gateway compatibility.
