# Changelog

All notable changes to Bifrost are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.3.0] – 2026-11-26

### Added
- **Patterns tab** – Bifrost finds steps that happen again and again, in the same order, in the hour before you leave, come home or go to sleep (e.g. calendar entry → front door → phone leaves). Shown as a step chain in a "cyber" style: timeline with T-minus times, accuracy ring, key figures, live progress and a plain-language summary. Suggested after 5+ observations with at least 85 % accuracy; switch each pattern on or off. Mining runs every 6 hours or on demand ("Find patterns now").
- **Drift check** – a switched-on pattern whose accuracy drops by more than 10 points, or that is no longer found, is marked "Changed".
- **Pattern entities** – `binary_sensor.bifrost_pattern_<id>` for every switched-on pattern (on when all steps happened; attribute `progress`). A matched pattern is also listed as a reason; it never changes the decision on its own.
- **Calendars tab** – Bifrost compares the entries of the last 6 weeks with its own decisions and learns which keywords mean "nobody is home". Active entries with such a keyword are listed as a reason. Full titles are never stored, only single keywords and counts. New option `learn_calendars` (on by default).

## [0.2.0] – 2026-11-26

### Added
- **Dashboard tab** – how the last 14 days went (share of each state per day), average confidence per day, "Is learning helping?" (Away decisions that ended within 15 minutes, fewer is better) and a sensor trust list.
- **Timeline tab** – every change of a used signal and every Bifrost decision of the last 24 hours, grouped by hour, filterable by category.
- **Learning per sensor** – Bifrost checks every signal against confirmed periods (same state for 30 minutes with at least 85 % confidence). Sensors that keep firing while the house is empty (pets, robots, drafts) stop counting as activity once they have 5+ observations and less than 30 % trust. New option `use_learning` (on by default).
- **Guest mode** – switch in the Status tab; while on, Bifrost never says the house is empty.
- **Faster setup** – "Use all suggestions" per category in Signals; filter by area and integration in Setup.
- **New entities** – `sensor.bifrost_expected_return` (typical return time on this weekday, learned from the last 8 weeks), `binary_sensor.bifrost_anomaly` (activity while every tracked phone is away), `binary_sensor.bifrost_guest_mode`, `sensor.bifrost_person_*` (home/away per person).

### Changed
- Times in the timeline use the 24-hour format; new logo in the app bar.

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
