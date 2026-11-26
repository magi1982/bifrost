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

### Second opinion – simple learning for every state (part of v0.4)
A small model that gives a probability for every state. **Home, Asleep and Away exclude each other** – the house is always in exactly one of them, so these three add up to 100 %. **Leaving soon and Arriving soon** can happen on top of that (home *and* about to leave), so each has its own 0–100 %. Pure Python (multinomial logistic regression / softmax), trained on the HA host in about a second – no GPU, no extra libraries.

- **States:** Home / Asleep / Away (softmax, together 100 %) plus Leaving soon and Arriving soon (separate yes/no models: will it happen within the next 15 min?). Unknown = the model is unsure (highest of the three below a threshold).
- **Features:** time of day (circular), weekday, minutes since last activity, phones away, lights/media on, power use, bedroom/kids' room activity, calendar keywords, guest mode, pattern progress, expected return.
- **Labels:** confirmed periods for Home/Asleep/Away; departures and arrivals for Leaving/Arriving – later ground truth from Loxone (0.5).
- **Shown:** distribution bar next to the rule result, top +/− reasons per state, 24 h chart of the probabilities, accuracy and calibration per state.
- **Rules too:** the rule engine also reports a distribution, so both opinions can be compared state by state.
- **Safety:** shadow only – it never changes the decision. Options `second_opinion` (on) and later `second_opinion_counts` (off by default, only after it has been better than the rules for several weeks).
- **Entities:** `sensor.bifrost_second_opinion` (most likely state, attributes: all probabilities, top reasons) and `sensor.bifrost_probability_home|asleep|away` (%, together 100) and `sensor.bifrost_probability_leaving_soon|arriving_soon` (%, each on its own).

### One decision from everything – expert fusion (part of v0.4)
Rules, every pattern and the learned model are **experts**. Each votes only when it applies, and each vote counts as much as that expert has earned by being right before. Safety rules stay above everything.

1. **Safety layer (veto):** guest mode, sleep mode, fail closed on missing data, shadow mode, never disarm – no expert can outvote it.
2. **Start value:** how often the house is in this state at this weekday/time.
3. **Experts vote:** rules (always, weighted by data health), each pattern (only while running, weighted by steps done / steps), learned model (always, weighted by proven accuracy).
4. **Combine in log-odds:** `logit P = logit(start) + c · Σ wᵢ (logit pᵢ − logit start)`, c ≈ 0.7 dampens experts that use the same sensors. A pattern's probability is `(right+1)/(seen+2)` – 23/23 gives 96 %, never 100 %.
5. **Weights learn (sleeping experts / Hedge):** after every confirmed outcome, experts that voted and were wrong lose weight, right ones gain; experts that did not vote are not judged.
6. **Calibration:** isotonic mapping over the last 4 weeks so that 90 % really means 90 %.
7. **Explained:** the Status tab lists every expert's vote, weight and pull, e.g. "Pattern #4F09B1 +1.9 · Learning −1.2 → 73 %, Unknown".

Behaviour: a strong running pattern dominates; when nothing fits, the learned model leads but alone it rarely reaches the 90 % needed for "empty"; when experts disagree the result drops to Unknown and both reasons are shown.

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
