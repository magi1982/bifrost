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

### Second opinion – simple learning (part of v0.4)
A small model that answers "how likely is the house empty right now?" from all signals at once. Pure Python (logistic regression, optionally a small decision tree), trained on the HA host in seconds – no GPU, no extra libraries.

- **Features:** time of day (circular), weekday, minutes since last activity, phones away, lights/media on, power use, calendar keywords, guest mode, pattern progress.
- **Labels:** confirmed periods (same state ≥30 min, ≥85 %) – later replaced by ground truth from Loxone (0.5).
- **Shown:** own percentage next to the rule result, top reasons as +/− weights, agreement with the rules, calibration ("when it said 80 %, it was right in 78 %").
- **Safety:** shadow only – it never changes the decision. New option `second_opinion` (on) and later `second_opinion_counts` (off by default) once it has proven better than the rules for several weeks.
- **Entity:** `sensor.bifrost_second_opinion` (%, attributes: top reasons).

Not planned now: neural networks (LSTM, transformers) – too few labelled examples (2–5 per day) and no explanation. Idea for much later: optional separate "Bifrost ML" app on stronger hardware, only as an extra opinion. HMM state smoothing stays an idea for later.

## v0.5 – Connections and setup assistant
- **Ground truth from Loxone:** alarm armed → disarmed by NFC = nobody home in between; presence detectors = somebody home. The second opinion and pattern accuracy learn from these real labels.
- **Setup assistant** – BLE on Shelly scanners, IRK explanation, fixed Wi-Fi address on iPhones, helpers and automations as signals.
- **Loxone connector (optional, read-only)** – person vs. automation for lights/blinds, presence blocks, alarm state.
- **UniFi connector (optional, read-only)** – client presence, guest Wi-Fi count, DPI at category level (streaming, gaming).

## v0.6 – Where in the house
- **House map** – upload a floor plan (stored locally only), place rooms and sensors, live view with activity and people.
- **BLE room location** – room fingerprints from BLE scanners; `sensor.bifrost_room_*`.

## v1.0 – Act (later)
- Release gate: 30 days shadow mode, ≥20 departures, 0 wrong "empty" decisions, data health ≥90 %.
- Only then: signal "house empty confirmed" to the alarm system. The alarm system arms itself. **Never disarm automatically.**
