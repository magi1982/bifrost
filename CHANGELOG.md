# Changelog

All notable changes to Bifrost are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

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
