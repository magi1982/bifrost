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

## Data review (Nov 2026) – revised order ⭐

A review against real household data showed: only 1 of 5 people is reliably visible today, the garage is the main entrance, children's rooms have no motion sensors, some sensors never fire, and a recurring school calendar keeps "school" entries during holidays. Therefore: **make every person visible and get ground truth first, add clever experts after.** The v0.4–v0.6 items below keep their content but follow this order.

### Principle: works in any house
Nothing house-specific is hard-coded (rooms, doors, names). Bifrost observes, discovers, proposes with a reason ("in 23 of 25 cases …") and the user confirms with one tap. Only what cannot be measured is asked once (household members, who has no phone, who may be home alone, guest rules, privacy). HA areas/floors and entity names are only the starting guess.

### Yggdrasil · house map (self-discovery, new layer before the experts)
- **Entrances:** a door opens → an indoor motion sensor fires within seconds → that sensor belongs to this entrance.
- **Inside vs outside:** a motion sensor that fires *before* a door opens, or while the house is confirmed empty, is outside.
- **Main entrance:** ranking of doors by real use (e.g. garage before front door).
- **Door direction:** outside → door → inside = in; inside → door → outside → silence = out.
- **Room map:** motion sensors that often fire shortly after each other are neighbours → adjacency graph, shown in a "House" tab.
- **Blind zones:** rooms without sensors and members without phone → Bifrost is more careful there and suggests hardware (ESP32/BLE).
- **Garden instead of away**, **noise sources** (robot, wind, pets), **dead/chatty sensors**, **device ↔ person**, **calendar ↔ person**, **day type**.
- Everything appears in a new "Suggestions" tab; nothing is used before it is confirmed or has strong evidence.

### Revised order
- 0.4 Understand: Yggdrasil basics (entrances, inside/outside, door direction, sensor doctor), Family tab + Frigg, Suggestions tab.
- 0.5 Truth: last-out rule, family balance, labels from hindsight/Loxone/push question, balance tab + backtesting.
- 0.6 Learn: calendar learning 2.0, missing patterns, day type, Huginn/Verdandi/Skuld.
- 0.7 → 1.0: room map + BLE location, Forseti fusion, Loki, CO₂, Gjallarhorn.

### Layered events (clarified architecture)
One pattern engine, used on several levels – higher levels use the events of lower levels as steps:
1. **Raw signals** (Ratatoskr).
2. **House building blocks** (Yggdrasil): small, stable patterns that are true for the house regardless of person or time, e.g. "entry via garage" (outside motion → door → indoor motion), "exit via front door", "in the garden". Confirmed once.
3. **Person events** (Frigg, bookkeeping – not a voting expert): house building block + a phone/BLE companion in the time window = "person A came home". Without a phone or tag the event stays "someone came home".
4. **Everyday patterns** (Muninn): habits built from levels 2–3, therefore shorter and more robust ("entry via garage" is one step instead of four raw ones).
- **What is "normal":** every level keeps its own statistics from history (counts, time spans). Skuld and Verdandi read the same events and keep their own statistics (arrival times, durations); no expert needs another expert's opinion as input.
- Safety rules (last out, family balance) use only levels 2–3, never habits.
- **Patterns consist of facts only, never of opinions:** steps may be raw signals, house building blocks or person events; expert outputs (e.g. "85 % empty") are never steps – avoids circular learning.
- **Drill-down UI:** a sub-pattern inside a pattern is a clickable card (level, count, preview of its steps); opening it shows its own chain; a breadcrumb leads back.
- **Patterns overview:** speaking names ("Person A · weekday evening arrival by car"), owner (person, family, house), type (arriving, leaving, at home, going to sleep, getting up, house building block), level and status (active, suggestion, changed); filter chips, search, counters; grouped by type.
- **Collapsible sub-patterns:** inside a pattern every sub-pattern can be expanded/collapsed inline (nested), "expand all / collapse all", and "Open ↗" jumps into the sub-pattern's own page with breadcrumb.
- **Asymmetry:** a recognised entry (level 2) sets "not empty" immediately via the gate – no vote needed. A 99 % departure pattern is only a loud Muninn vote inside the capped habit group; "empty" still needs the family balance and the last-out rule.

### Entry guard (suspicious entries) – idea
- **Every entry must be explained:** known phone/BLE arriving, NFC disarm at the keypad, somebody was already inside (inside motion before), a learned pattern (e.g. regular visitor), or guest mode. Otherwise: unexplained entry.
- **Door profiles learned by Yggdrasil (no names needed):** per door/window how often it is used as entry from outside, as exit, or only opened from inside (ventilation, garden), by time of day. The entity name and HA device class are only a first hint; the role comes from behaviour and is shown as a suggestion ("door X is almost only opened from inside – garden door?").
- **Rarity:** Loki compares an entry with the door profile ("0 of 400 entries through this door at night") → raises the suspicion level. Heimdall reports the event, Loki judges how unusual it is.
- **Works from day one:** "entry from outside while asleep/empty and nothing explains it" needs no history; door profiles only sharpen it. Without an inside sensor near a door the direction is "unknown" and handled conservatively.
- **Levels (configurable):** hint (push "was that you?"), warning (`binary_sensor.bifrost_suspicious_entry` for own automations), later a "suspicion" signal to the alarm system via Gjallarhorn. Never disarms, never controls the alarm; complements the alarm system when it is not armed.

### Must-have: calendar learning 2.0 (Mímir · calendar)
- Learn **every frequently used word** (≥5 occurrences) in all chosen calendars – not only "word → house empty".
- **Five effects per word:** person away · person home · house empty · a known pattern does not happen · day type (school day, holidays, weekend, home office).
- **Person attribution:** names from the Family tab found in a title assign the entry to that person, whatever calendar it is in. A shared family calendar is fully usable.
- **All-day / multi-day entries** (trip, holidays) are day context, not appointments.
- **Recurring series** (e.g. school) are a plan that is checked against reality every day; if the pattern does not happen on many consecutive days and a word like "holidays" is active, Bifrost proposes "word = no school".
- Entries can also mean **at home** (e.g. a morning workout) – learned in both directions.
- Proposals need confirmation; only words and counters are stored, never full titles. Built-in, editable **block list for sensitive words** (health, doctor) – never learned, never shown.

### Patterns 2.0 – real-life sequences (Muninn)
Example to support: car arrives → garage gate → outside motion at garage → door → indoor motion at entrance → hallway *or* storeroom, with one or more phones arriving via Wi-Fi/BLE somewhere in between.
- **Core chain + companions:** a fixed-order core and companion events that may happen anywhere in a time window (e.g. "phone arrives between −3 and +2 min").
- **Alternative steps (OR):** "hallway or storeroom" merged into one pattern instead of two weak ones.
- **Longer chains:** more than 5 steps when the evidence supports it.
- **Rare but strong tokens** (car, gate) are not dropped by the "top 10 most frequent" limit; selection by information value, not only frequency.
- **Building blocks:** THEN (order, learned time span min–typical–max), AND (all, any order, within a window), OR (one of), COMPANION (any time in a window), OPTIONAL (usually present). Similar chains are merged into one process plan instead of hundreds of chains.
- **Review in the chain view:** new patterns appear as a suggestion ("does not vote yet") with Yes / No / Adjust / Later; "No" also suppresses similar suggestions; drift ("fits worse since 2 weeks") asks again.
- **Early detection:** a partially completed chain already says "arrival in progress" / "departure in progress".
- **What it teaches the other layers:** door direction and entrance geometry (Yggdrasil), who arrived via phone/BLE (Frigg), arrival times (Skuld). A pattern cannot count how many people arrived without phones or tags.

### Family tab + Frigg (family) – the core
- Household members with: phone (person/tracker) or none, own calendars, "may be home alone: yes/no", room, optional BLE tag, school schedule (from a calendar or a timetable entity).
- Per-person "home" probability; **house empty only if every person is accounted for**. A member without phone counts as home until proven away (with an adult, schedule + exit, tag).
- Suggestions: persons from HA, calendar owner by name, learned link "entry ↔ whose phone leaves".

### Safety rules (before any fusion)
- **Last-out rule:** an exit through front door, garage door or garage gate, then no indoor motion/presence for N minutes; garden/terrace doors are not exits.
- **Door direction:** motion before the door then silence = out; door then motion = in.
- **Habit speeds up, never proves:** all habit experts together count as one capped vote; without the two rules above the result stays at most Unknown.
- Loxone safety net (documented recommendation): pre-warning with cancel, start with perimeter-only arming.

### Ground truth and measurement (moved up)
- Loxone alarm state + NFC events as labels (read-only user); optional push question "House empty?" between 75 and 90 %.
- Hindsight labels: "empty" confirmed by an entry from outside before any indoor motion; refuted by indoor motion without entry.
- **Backtesting** of every new rule/expert against stored history; dashboard KPIs: false "empty" per month (target 0) and share of empty time detected.
- Bifrost keeps its own raw event history longer than the HA recorder (10 days).

### Sensor doctor
- Report dead sensors (never active), chatty sensors (far more changes than others), phones with changing Wi-Fi address, trackers almost never "home".

### More data sources (later)
- Central ventilation CO₂ as "breathing" signal (falling steadily → probably nobody home) – test first.
- Devices of members without phone (tablet, room speaker, TV) as presence hints.
- Day type from an official school-holiday calendar and a holiday integration.
- **ESP32** BLE receivers indoors (ground/upper floor) and optional Wi-Fi probe sniffing; BLE tags for members without phone.
- Family planner integration: optional timetable entities per child (in school / school holidays).

### Expert names and icons
Heimdall · watcher, Frigg · family (new), Muninn · memory, Mímir · calendar, Huginn · thinker, Verdandi · rhythm, Skuld · foresight, Loki · doubter, Forseti · judge, Himinbjörg · gate, Gjallarhorn · signal (later), Ratatoskr · data messenger (not an expert). Shown in the app as "Name · plain name" with one line icon each.

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

### More experts (part of v0.4)
- **Semi-Markov state model:** knows the usual duration of each state and the usual transitions (e.g. asleep 6–8 h, asleep → away almost never at night). Smooths short flapping, makes "Asleep" much more reliable, notices when something lasts unusually long or short. Explained as "asleep for 2 h, usually 7 h → stays Asleep". Pure Python, little data.
- **Time-to-event model (survival analysis):** per person and weekday, the chance that somebody comes home or leaves within the next 15 minutes, and the expected return time with range ("17:35, usually 17:10–18:05"). Feeds "Arriving soon", "Leaving soon" and `sensor.bifrost_expected_return`.

Not planned now: neural networks (LSTM, transformers) – too few labelled examples (2–5 per day) and no explanation. Idea for much later: optional separate "Bifrost ML" app on stronger hardware, only as an extra opinion. HMM state smoothing stays an idea for later.

## v0.5 – Connections and setup assistant
- **Doubter expert (anomaly):** isolation forest or simple z-scores over the current situation. It does not vote for a state; when today looks unusual it lowers the weight of all other experts so Bifrost says Unknown instead of being wrongly sure. Also drives `binary_sensor.bifrost_anomaly`.
- **Ground truth from Loxone:** alarm armed → disarmed by NFC = nobody home in between; presence detectors = somebody home. The second opinion and pattern accuracy learn from these real labels.
- **Setup assistant** – BLE on Shelly scanners, IRK explanation, fixed Wi-Fi address on iPhones, helpers and automations as signals.
- **Loxone connector (optional, read-only)** – person vs. automation for lights/blinds, presence blocks, alarm state.
- **UniFi connector (optional, read-only)** – client presence, guest Wi-Fi count, DPI at category level (streaming, gaming).

## v0.6 – Where in the house
- Particle filter for BLE room location (a data source for the experts, not an expert itself).
- **House map** – upload a floor plan (stored locally only), place rooms and sensors, live view with activity and people.
- **BLE room location** – room fingerprints from BLE scanners; `sensor.bifrost_room_*`.

## v1.0 – Act (later)
- Release gate: 30 days shadow mode, ≥20 departures, 0 wrong "empty" decisions, data health ≥90 %.
- Only then: signal "house empty confirmed" to the alarm system. The alarm system arms itself. **Never disarm automatically.**
