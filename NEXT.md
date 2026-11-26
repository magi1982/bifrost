# NEXT – roadmap

All items below were approved by the maintainer for the next versions. Built one version at a time.

## v0.2 – See and learn ✅ (released in 0.2.0)
- **Dashboard tab** – charts: detected state per day, confidence over time, "is learning helping?" curve.
- **Timeline tab** – what happened today, grouped by category (doors, motion, phones, modes …).
- **Learning per sensor** – store state changes locally; per-signal trust (Beta-Bayes): how often did a signal agree with the later confirmed result.
- **Faster setup** – accept all suggestions of a category at once; filter by area and integration.
- **More own entities** – `sensor.bifrost_expected_return`, `binary_sensor.bifrost_anomaly`, `binary_sensor.bifrost_guest_mode` (toggle in the app; a real switch needs a small custom integration – later), `sensor.bifrost_person_*`.

## v0.3 – Patterns and calendars ✅ (released in 0.3.0)
- **Patterns as processes** – sequences of 3–5+ steps with typical times between them (e.g. calendar entry → phone leaves → front door → no motion). Suggested at ≥5 observations and ≥85 % accuracy, switchable on/off, weekly drift check, `binary_sensor.bifrost_pattern_*`.
- **Calendar learning** – which calendars and keywords mean "away"; birthday calendars ignored; titles are never stored.

## v0.4 – Complex patterns (pattern recognition, lightweight)
Only methods that run on the Home Assistant host with the Python standard library and can explain every result. No neural networks, no heavy libraries.

| Method | What it adds | Shown as |
|---|---|---|
| **Episode mining** (WINEPI-style time windows) | Steps that happen together in any order – **AND** | "Person A **and** Person B leave" |
| **Heuristics process mining** (follows-relations with frequency thresholds) | Alternatives and optional steps – **OR**, **optional** | "light off **or** coffee off", dashed "garage (optional)" |
| **Absence patterns** | Something must **not** happen for a while – **NOT** | "no motion for 10 min" |
| **Association rules with lift** (Apriori on context items) | Conditions under which a pattern holds – **Only when** | "Mon–Thu · 06:45–08:30 · calendar says school · guest mode off" |
| **Circular time statistics** (mean/spread on the 24 h circle) | Usual time ± spread, better expected return | "usually 17:35 ± 20 min" |
| **Page–Hinkley drift test** | Statistically sound "Changed – check" instead of a fixed −10 points rule | drift chart per pattern |
| **Discovered patterns** | New outcomes found automatically (e.g. bedtime routines) with "Switch on / Not useful" | "New – found by Bifrost" |

Database additions: `pattern_steps` (pos, logic ONE/AND/OR/NOT, optional, gap median/p10/p90, hit rate), `step_sources` (entity, expected state, side in/out), `pattern_matches` (every run, right or wrong, miss reason), `pattern_checks` (history of each re-check for drift). `patterns` gains `conditions` and `origin`.

UI: pattern view with **Simple / Technical** switch, friendly names, **i** button per step (entity IDs, source, timing, trust, rule), works on phones (vertical chain, sources from the side), light and dark.

Not planned: neural networks (LSTM, transformers) – no explanation, too heavy. HMM state smoothing stays an idea for later.

## v0.5 – Connections and setup assistant
- **Setup assistant** – BLE on Shelly scanners, IRK explanation, fixed Wi-Fi address on iPhones, helpers and automations as signals.
- **Loxone connector (optional, read-only)** – person vs. automation for lights/blinds, presence blocks, alarm state.
- **UniFi connector (optional, read-only)** – client presence, guest Wi-Fi count, DPI at category level (streaming, gaming).

## v0.6 – Where in the house
- **House map** – upload a floor plan (stored locally only), place rooms and sensors, live view with activity and people.
- **BLE room location** – room fingerprints from BLE scanners; `sensor.bifrost_room_*`.

## v1.0 – Act (later)
- Release gate: 30 days shadow mode, ≥20 departures, 0 wrong "empty" decisions, data health ≥90 %.
- Only then: signal "house empty confirmed" to the alarm system. The alarm system arms itself. **Never disarm automatically.**
