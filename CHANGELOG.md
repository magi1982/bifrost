# Changelog

All notable changes to Bifrost are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.5] – 2026-11-26

### Fixed
- Switching entities on/off and changing category or role in Setup did not save through Home Assistant Ingress (request bodies arrive chunked). Chunked bodies are now supported, still limited to 4 KB.
- Saving now shows a short confirmation or error message (alerts are blocked in the Home Assistant app).

## [0.1.4] – 2026-11-26

### Fixed
- Switches from network integrations (UniFi, FRITZ!Box, Omada, MikroTik, Pi-hole, AdGuard, OPNsense, pfSense) are ignored. A guest Wi-Fi switch was wrongly treated as guest mode and kept the house "Home" forever.

## [0.1.3] – 2026-11-26

### Fixed
- App did not start ("No Home Assistant token available"): the start script now passes the Supervisor environment to the app (`with-contenv`), with a fallback that reads the token from the s6 container environment.

## [0.1.2] – 2026-11-26

### Security
- **Fail closed:** Bifrost no longer reports "Away"/house empty without phone or person trackers, without activity sensors, or when less than 60 % of the selected signals are available. It reports "Unknown" instead.
- An included entity that disappears from Home Assistant now counts as unavailable and lowers data health.
- Confidence is capped at 80 % when only one activity sensor confirms the result.
- POST requests require a JSON content type and the `X-Bifrost-Request` header (CSRF protection).
- Web server limits parallel connections (16) and times out idle connections (10 s).
- Entity overrides are only stored for entities found by the scanner.

### Fixed
- A motion sensor that just switched off now counts as recent activity (previously ignored, which could shorten the waiting time before "Away").

## [0.1.1] – 2026-11-26

### Added
- App icon and logo: a three-coloured bridge (fire, gold, sky) from your home to the stars.

## [0.1.0] – 2026-11-26

### Added
- First experimental Home Assistant app (ingress panel, light and dark theme).
- **Scanner**: reads all entities, devices and areas from Home Assistant (enabled, disabled and unavailable).
- **Sensor configurator**: suggests a category (12 categories) and a role (Evidence, Trigger, Context, Blocker, Noise, Truth) for every entity, with plain-language reasons. Users can switch entities on/off and correct the guess; corrections are kept.
- **Decision engine** (rules, no learning yet): Home, Asleep, Leaving, Away, Arriving, Unknown, with confidence, reasons and data health.
- **Entities for your automations**: `sensor.bifrost_home_status`, `binary_sensor.bifrost_house_empty`, `sensor.bifrost_confidence`, `sensor.bifrost_reason`, `sensor.bifrost_data_health`.
- **Shadow mode** (default on): Bifrost only observes. It never arms or disarms anything.
- Options: update interval, phone-away wait, no-motion wait, shadow mode, publish entities, log level.
- 24-hour history of detected states (local SQLite, 90 days retention).
- CI: tests, ruff, bandit, Home Assistant app linter, secret scan, Dependabot.
