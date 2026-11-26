# Security policy

## Reporting a vulnerability
Please **do not open a public issue**. Use GitHub's private vulnerability reporting (Security → Report a vulnerability) on this repository. You will get an answer within 7 days.

## Design principles
- **Local only.** Bifrost talks only to your own Home Assistant. No cloud, no telemetry, no external calls.
- **No secrets in code or logs.** The only credential is the `SUPERVISOR_TOKEN` provided by Home Assistant at runtime. It is never logged or stored. Future connector keys (UniFi, Loxone) will be stored only in the app's private `/data` folder.
- **Least privilege.** The app requests `homeassistant_api` only (read states/registries, write its own `bifrost_*` entities). No `hassio_api`, no host network, no privileged mode, no extra ports – the UI is reachable only through Home Assistant Ingress.
- **Ingress only.** The web server rejects every client except the Ingress proxy (`172.30.32.2`).
- **Strict input validation.** All API input is size-limited (4 KB) and checked against allow-lists (entity id pattern, status, category, role). Only bundled static files are served.
- **Fail closed.** Missing or unavailable data leads to "Unknown", never to "house empty".
- **CSRF and resource limits.** POST needs JSON plus a custom header; at most 16 parallel connections with a 10 s timeout.
- **Browser hardening.** Content-Security-Policy, `nosniff`, `no-referrer`, `no-store`; all values are HTML-escaped in the UI.
- **No dependencies.** The app uses the Python standard library only, which removes supply-chain risk from third-party packages.
- **Never disarms.** Bifrost will never disarm an alarm. Future versions may only *signal* "house empty confirmed" to your alarm system, and only after you switch shadow mode off.

## Threat model (short)
| Threat | Mitigation |
|---|---|
| Someone on the LAN calls the API | Only the Ingress IP is accepted; HA authentication protects Ingress |
| Spoofed BLE/Wi-Fi signals make the house look empty | Spoofable signals never decide alone; shadow mode by default; arming is done by the alarm system, disarming only by the owner |
| Token leak through logs | Token never logged; error messages contain no headers |
| Malicious entity names (XSS) | All names are escaped; CSP blocks external scripts |
| Private data in the public repository | Examples use invented names; floor plans and scan results are git-ignored; secret scan in CI |
