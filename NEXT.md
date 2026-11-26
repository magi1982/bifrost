# NEXT – roadmap

All items below were approved by the maintainer for the next versions. Built one version at a time.

## v0.2 – See and learn
- **Dashboard tab** – charts: detected state per day, confidence over time, "is learning helping?" curve.
- **Timeline tab** – what happened today, grouped by category (doors, motion, phones, modes …).
- **Learning per sensor** – store state changes locally; per-signal trust (Beta-Bayes): how often did a signal agree with the later confirmed result.
- **Faster setup** – accept all suggestions of a category at once; filter by area and integration.
- **More own entities** – `sensor.bifrost_expected_return`, `binary_sensor.bifrost_anomaly`, `switch.bifrost_guest_mode`, `sensor.bifrost_person_*`.

## v0.3 – Patterns and calendars
- **Patterns as processes** – sequences of 3–5+ steps with typical times between them (e.g. calendar entry → phone leaves → front door → no motion). Suggested at ≥5 observations and ≥85 % accuracy, switchable on/off, weekly drift check, `binary_sensor.bifrost_pattern_*`.
- **Calendar learning** – which calendars and keywords mean "away"; birthday calendars ignored; titles are never stored.

## v0.4 – Connections and setup assistant
- **Setup assistant** – BLE on Shelly scanners, IRK explanation, fixed Wi-Fi address on iPhones, helpers and automations as signals.
- **Loxone connector (optional, read-only)** – person vs. automation for lights/blinds, presence blocks, alarm state.
- **UniFi connector (optional, read-only)** – client presence, guest Wi-Fi count, DPI at category level (streaming, gaming).

## v0.5 – Where in the house
- **House map** – upload a floor plan (stored locally only), place rooms and sensors, live view with activity and people.
- **BLE room location** – room fingerprints from BLE scanners; `sensor.bifrost_room_*`.

## v1.0 – Act (later)
- Release gate: 30 days shadow mode, ≥20 departures, 0 wrong "empty" decisions, data health ≥90 %.
- Only then: signal "house empty confirmed" to the alarm system. The alarm system arms itself. **Never disarm automatically.**
