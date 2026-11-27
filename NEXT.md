# NEXT – roadmap

## 1 · Status
- **0.2.0** – released and running (rules, per-sensor trust, dashboard, timeline).
- **0.3.0** – built and tested, **not released yet** (simple patterns, calendar keywords).
- **0.4.0** – built and tested, **not released yet**: the roadmap 0.4–1.0 below is implemented in one go (163 tests, synthetic household, GUI check). Still open, see the `⏳` marks: Loxone read-only connector (alarm state, NFC user), push question, real ESP32/IRK scanners, CO₂ test, backtesting on real data. The alarm signal stays off until the release gate is green on real data.
- Everything below is the agreed concept. It is built **one version at a time**; every version is released only after the maintainer's OK.

## 2 · Principles
- **Works in any house.** Nothing house-specific is hard-coded (rooms, doors, names). Bifrost observes, discovers, proposes with a reason ("in 23 of 25 cases …") and the owner confirms. Only what cannot be measured is asked once.
- **Safe first.** Rather "Unknown" than a wrong "empty". A wrong "home" is only inconvenient.
- **Patterns consist of facts only**, never of opinions – no circular learning.
- **Never disarms**, never controls the alarm system directly.
- **Local and private.** All data stays in the app's own storage; no full calendar titles; keys (IRK) never in logs, exports or code.
- **No hand-written special cases.** Only generic mechanisms are coded; concrete names ("phone forgotten", "cleaner") come from the owner.

## 3 · Overall logic – three parts

```
Data ──▶ PATTERN RECOGNITION ──▶ GUARD ──▶ RESULT
         learns everything        fixed      status, %, questions,
         🧱 Blocks                rules      later signal to alarm
         👤 People                (never
         🔁 Routines               learned)
         ⚠ Deviations
             ▲                                   │
             └──────────── labels ◀──────────────┘
```

Every minute three questions, in this order:
1. **Is somebody certainly home?** (facts: entry detected, indoor motion, a person's phone home, sleep or guest mode) → yes = Home / Asleep, done. No vote needed.
2. **May the house be empty at all?** (guard: every person accounted for, unknowns = 0, last-out rule, data healthy) → no = Unknown with reason, done.
3. **How sure and how fast?** (routines, timing and deviations give a calibrated %) → ≥ 90 % Empty · 75–90 % push question · below Unknown.

In parallel the guard watches entries: an entry nothing explains becomes a hint → warning → (later) signal.

## 4 · Terms
- Tab **Pattern recognition** (DE: Mustererkennung) with three types:
  - 🧱 **Blocks** (Bausteine) – how the house works, valid for everyone: entries/exits per door, door direction, neighbours and walking times, garden, known disturbances.
  - 👤 **People** (Personen) – a block plus an identity (phone, BLE/IRK, NFC user, tag) = who.
  - 🔁 **Routines** (Abläufe) – habits with conditions (weekday, time window, calendar words).
- ⚠ **Deviations** (Abweichungen) are **not a pattern type** but a list of moments that did not fit (open / explained). Answering one turns it into a pattern or exception: e.g. a cleaner → person "regular visitor" + routine; animals → block of kind "disturbance" (shown as known exception). Unanswered ones stay open or expire.
- **Goal** of a pattern: arriving, leaving, at home, going to sleep, getting up, house.
- **Chain parts:** THEN (order, time span min–typical–max) · AND (any order within a window) · OR (one of) · NOT (must not happen for a while) · COMPANION (any time in a window) · OPTIONAL (usually present).
- **Nesting:** a type may contain smaller types and its own type (block in block, routine in routine), never upwards; the type follows from the content. No pattern contains itself. UI expands ~4 levels inline, deeper via "Open". The word "level" is not used in the UI.
- Tab **People** (Personen) – the only place where persons are defined (no HA persons/users needed).

## 5 · Roadmap
### 0.4 · Understand
- Event pre-processing (§6.1) and own long event history.
- People tab with sources per person; person ledger incl. "unknown: at least N".
- Blocks: entries/exits, inside/outside, door direction, door profiles, neighbours + walking times, duplicates, disturbances; sensor doctor.
- House map (learned graph) in a "House" tab.
- Suggestions + Questions inbox (answers Yes / No / Maybe / Don't know).
- Pattern recognition tab: overview, filters, collapsible sub-patterns, "Open", step/sensor/logic counters.
- Learning phase, restart behaviour, capability check, re-evaluation on new sources.
### 0.5 · Safe and true
- Guard rules (§6.3), explanation strength, suspicious-entry levels 1–2.
- Labels: hindsight, "That's wrong" button ✅, ⏳ push question, ⏳ Loxone read-only (alarm state, NFC with user).
- Balance tab ✅; simulator household as release test ✅; ⏳ backtesting on real data.
### 0.6 · Learn
- Routines 2.0 with all chain parts and pattern hygiene (§6.2.4).
- Calendar learning 2.0, day type, holidays.
- Timing (arrival times, durations), "arriving soon" / "leaving soon".
- Deviations: expectation list, rarity, learned negatives, contradictions, owner labels.
### 0.7 · Where in the house
- BLE fingerprints and access point place ✅ (logic); ⏳ real ESP32 scanners with IRK identities.
- Optional floor plan ✅; ⏳ CO₂ "breathing" signal (logic ready, test on real data first).
### 1.0 · Act
- Release gate: 30 days shadow mode, ≥ 20 departures, 0 wrong "empty", data health ≥ 90 %.
- Signal "house empty confirmed" and "suspicion" as entities ✅ (off by default); ⏳ wiring to the alarm system in Loxone. **Never disarm.**


### Next version · Bluetooth check – which Bluetooth entities make sense (requested 27.11.)
Goal: with Shelly proxies, Private BLE Device, Bermuda or iBeacon a house quickly gets dozens of Bluetooth entities (one distance and one signal strength per scanner and device, trackers for TVs, watches, neighbours' phones). Bifrost recognises by itself which of them help and suggests the rest to switch off.

**Kinds Bifrost recognises (HA standards, integration as fallback)**
- *Presence of a device*: `device_tracker` with `source_type: bluetooth_le` (Private BLE Device, iBeacon) → useful as a person source.
- *Room of a device*: Bermuda "Area" sensor → useful as a room source (already used for avatars).
- *Distance / signal strength per scanner*: Bermuda `distance_to_*`, `*_rssi`, Private BLE `*_signal_strength` / `*_estimated_distance` → raw values; noisy, Bifrost does not need them once a tracker or area exists → suggest switching off.
- *Scanner itself*: Shelly / ESP Bluetooth proxy entities → not a signal of presence.

**Checks per Bluetooth device (learned, no setting)**
- *Moves with a person*: comes home / leaves within minutes of a phone or an access code that belongs to a person (co-occurrence ≥ 80 % over ≥ 5 arrivals) → suggest "belongs to <person>".
- *Stationary*: practically always "home" for weeks, never away (TV, speaker, a fridge, the neighbour's device behind the wall) → "not a person – switch off?".
- *Rarely seen / flapping*: appears briefly and disappears (passers-by, random addresses) → "brings nothing".
- *Room reliability*: how often the area changes within a minute (ping-pong between two scanners) → if high, the room is shown only as "in the house" (already the avatar rule) and the source counts as weak.
- *Coverage*: rooms that no scanner ever reports → hint "no Bluetooth scanner here".

**UI**
- Setup card "Bluetooth" (replaces the help card when Bluetooth entities exist): devices found, per device the verdict (person source / room source / stationary / rarely seen / raw value) and the suggested action; one-tap "belongs to" suggestion.
- The existing filters "Brings nothing" / "Slow" also cover Bluetooth raw values.

**Limits**
- iPhones only appear with their IRK in Private BLE Device; without it they are random addresses and can only be "rarely seen".
- Co-occurrence needs a few arrivals per person (about a week).

**Open questions**
1. Suggest switching off raw distance/RSSI entities in one go ("switch off all 24 raw values"), or one by one?
2. Should a stationary device that is "home" exactly when somebody is home (e.g. a laptop) be offered as a weak person source?

**Tests**: classification of Bermuda / Private BLE / iBeacon entity names and attributes, co-occurrence suggestion on the simulator, stationary and flapping devices, room ping-pong, GUI check.

**Extension (27.11.) · Raw devices the Shellys hear – "what is that?"**
Most devices the Shelly proxies hear never become an entity. Home Assistant still sees their advertisements (Settings → Bluetooth → advertisement monitor). Bifrost reads them read-only over the WebSocket (`bluetooth/subscribe_advertisements` – to be verified on the maintainer's HA version) and shows them in a Setup card **"Bluetooth devices nearby"**:
- **What it is** – from public identifiers, no guessing of persons: manufacturer from the company ID in the manufacturer data (e.g. 0x004C Apple, 0x0075 Samsung, 0x0006 Microsoft, 0x00E0 Google), service UUIDs (Fast Pair, Find My, Tile, BTHome, Xiaomi), Apple message type (iPhone/Watch "nearby", AirPods, Find My tag), the advertised name if any, TX power.
- **Where** – which Shelly hears it best and the signal strength (≈ room), how stable that is.
- **How often** – first/last seen, share of the day present, home/away rhythm compared with the phones; random-address devices are grouped ("12 changing Apple addresses") instead of listed one by one.
- **Verdict and action** – stationary (TV, speaker, neighbour) / moves with a person → "belongs to …?" / passer-by. If a device is useful, Bifrost says how to turn it into an entity (iBeacon, Private BLE Device with IRK, BTHome, Bermuda).
- **Privacy** – addresses stay in the app's own storage, are shown shortened, never exported or logged; devices seen < 3 times in a week are forgotten.
Limits: iPhones and modern Android phones rotate their address every ~15 min – without an IRK they can be counted and typed ("an Apple phone"), not identified. Needs the Bluetooth integration in HA with the Shellys as proxies (active scanning gives names).

**Concept v2 (27.11.) · Setup section "Bluetooth nearby" – what we can use it for** – mockup: private artifact "Bifrost Bluetooth"
*Data path.* Read-only WebSocket subscription to HA's advertisements. Advertisements arrive many times per second, so Bifrost aggregates in memory per device and minute (best scanner, RSSI, seen yes/no) and stores 5-minute buckets only. Caps: 500 devices, 14 days; a device unseen for 14 days is forgotten unless the owner named it. **Off by default** – switch "Record Bluetooth surroundings" with an explanation.

*Recognisable or not.* Each device gets "recognisable: yes / until restart / no" from its address type: public or static addresses (TVs, speakers, sensors, car kits, scanners, many fitness bands) are stable; phones rotate (resolvable private) and are only counted per type ("3 Apple phones nearby") – never followed.

*Groups (learned, no setting)*
- **House devices** – stationary, heard all day by the same scanner (TV, speakers, BTHome sensors). Use: scanner health ("Shelly garage no longer hears the freezer sensor").
- **Moves with a person** – comes and goes with a phone or code ≥ 80 % → "belongs to …?". Use: extra person source (watch, car kit, earbuds).
- **Regular visitors** – not stationary, seen on ≥ 3 different days in 4 weeks, stays < 30 min, first heard by an outdoor or entrance scanner, often at similar times (e.g. Mon–Fri 10:15–10:25). The owner names them ("Post", "Cleaner", "Grandma"). Use: explains an "unknown person" at the door, identity step in the incident chain ("approach: Post"), optional push "Post was here 10:22", `binary_sensor.bifrost_visitor_<slug>`.
- **Passers-by** – seen once or twice, weak signal, outdoor scanner only → hidden, only counted.
- **Phones nearby (anonymous)** – number of rotating Apple/Android phones in the house now vs. usual; a weak extra presence clue that needs no IRK (cannot see children without a phone, never decides alone).

*UI (Setup → "Bluetooth nearby")*: KPI row (scanners, devices now, regular visitors, phones nearby); filter chips per group; per device: type icon and label from public identifiers (manufacturer, Apple message type, service UUID, name), best scanner ≈ room with signal bar, 7-day rhythm strip, visits and typical time, verdict pill, actions *Name*, *Belongs to person*, *Ignore*, *Use as entity* (explains iBeacon / Private BLE Device / BTHome / Bermuda).

*Position (triangulation, 27.11.).* Every advertisement carries the scanner (source) and its RSSI, so for one device Bifrost gets a vector "Shelly hall −62, Shelly living −71, Shelly door outside −80 …". Geometric trilateration (RSSI → metres → circles) is poor indoors (walls, bodies, antenna direction, ±5–10 dB noise) – Bifrost uses **fingerprints** instead and learns them itself:
- each room gets a typical RSSI vector; calibrated automatically from stationary devices in rooms with a known area (TV in the living room) and from moments when only one room's motion sensor fires while a device is heard;
- a device is placed in the room whose fingerprint is nearest (k-nearest neighbours), with a confidence; below it only "in the house" / "outside" (same avatar rule as today);
- the most useful answer is **inside or outside**: a visitor device at the front door vs. in the hallway; this works with two scanners per entrance (one outside, one inside);
- optional: if the Shellys are placed on the floor-plan grid (House tab), the position is drawn as a soft dot between them – shown as an area, never as an exact point.
Accuracy to expect: room level (2–5 m) with ≥ 3 scanners hearing the device; Shelly scanning misses packets, so positions are smoothed over ~30 s. Rotating phones can be placed for as long as their address lasts (~15 min) – enough for "2 phones in the upper floor", never for following a person.
*Limits.* No guarantee: a postman is only found if they carry something with a stable address (handheld scanner, van, band); rotating phones are not recognisable. Bluetooth reach goes through walls – a neighbour can look like a "house device".
*Privacy.* Third-party devices are recorded only as type + shortened address, never exported, logged or sent anywhere; names come only from the owner; forgotten after 14 days. The owner is responsible for informing regular visitors where the law asks for it.
*Open questions.* Place the Shellys on the floor plan, or is their HA area enough? Off by default – yes? Retention 14 days – ok? Push for named visitors ("Post was here") – yes/no? Use "phones nearby" as a weak evidence signal or only display it?
*Tests.* Aggregation and caps; address-type → recognisable; grouping on a simulated week (TV, watch with a person, Mon–Fri visitor, passers-by, rotating phones); forgetting after 14 days; naming creates the visitor entity; no address in logs; GUI check light/dark/390 px.

### Done in 0.10.0 · Signal value – which sensors help, which are useless (requested 27.11.)
Decisions: only suggest switching off; useless/slow signals disappear from the House tab, a separate button shows the archived ones.
Goal: Bifrost reads every entity and learns by itself which signals help to tell "home" from "empty" – and which bring nothing (e.g. aggregated presence zones from another system that stay "on" for a long time, sensors that hardly change). Filterable in Setup.

**What Bifrost measures per signal (no setting needed)**
- *Information*: the evidence weight learned from hindsight (how much more often it fires when somebody is home than when empty). Near 0 = says nothing.
- *Activity*: state changes per day; *hold*: typical time it stays "on". A presence zone that stays on for an hour after the last person left is slow and says little about "right now".
- *Timeliness*: does it fire early in a path (first after a door) or only long after other sensors – aggregated zones come late.
- *Duplicate*: fires almost always together with another sensor (already detected) – one of the two is enough.
- *Doctor*: dead, chatty, often unavailable (already detected).

**Verdict per signal** (shown as a pill, with the reason): **Valuable** · **Helps a little** · **Brings nothing** · **Slow (zone)** · **Too few data**.

**Setup**
- New filter chips "Brings nothing" and "Slow / zone" next to the existing filters; the counts show at a glance how many signals are useless.
- Optimisation suggestion "Switch off – brings nothing (reason)". Bifrost never switches off by itself – the owner decides (option: later automatically after 30 days?).
- Card "What Bifrost sees" shows per kind how many are valuable.

**Limits**
- Needs hindsight labels: until the evidence scale is ready the verdict is "too few data" (except dead/chatty/duplicate, which work from day one).
- A sensor that only matters for one rare situation (e.g. a garden door in summer) may look useless in winter – the verdict uses the last 8 weeks and says so.

**Open questions**
1. Only suggest switching off, or also switch off automatically after a while?
2. Should signals that bring nothing still appear in the House tab (greyed out) or disappear there too?

**Tests**: verdicts on the simulator (a slow zone sensor that stays on for an hour, a dead sensor, a duplicate, a valuable motion sensor), filter counts, optimisation text DE/EN, GUI check.

### Done in 0.7.0 – 0.9.1 · Plan from the full review and proposal v2 (agreed 27.11., built 27.11.)
Done in 0.9.1: event lane per area (House tab), old 0.3 views, timeline/dashboard and the old chain CSS removed. Still open: tuning of the hindsight thresholds on real data (Balance shows the result).

Mockup: proposal page "Bifrost Vorschlag" (private artifact, example data). Decisions of the maintainer: avatars in rooms yes, one floor plan per floor, status shows Home / Asleep / Away + "in progress", Bifrost's own IRK store goes away (IRKs live in HA's Private BLE Device).

**Core idea:** Bifrost must not learn from its own decisions. Truth comes from hindsight facts, "That's wrong" and answers. Several detectors (like a security operations centre) check each other; Heimdall keeps the last word for "empty".

#### 0.7 · Safe foundation, HA standards, chain design
- Safety fixes (see "Safety fixes from the review" below): guard failure ⇒ Unknown + guard not ok; persist guard state + "Unknown – collecting" after restart; only an unexplained exit lowers unknowns; unmapped access value = medium, not strong; "That's wrong" on a wrong "empty" sets unknowns ≥ 1; exit only with confirmation (outside motion, phone leaves, lock from outside, car leaves) – otherwise "door used, direction open".
- **Visibility per person, derived automatically** from the assigned sources: good (GPS phone `source_type: gps`, BLE with room, code/NFC), medium (`source_type: router`, BLE without room), invisible (no source). Strength from the HA standard `source_type`, no longer from a list of integration names. Invisible persons count as home until facts say otherwise (learned companionship "leaves with person B", calendar words with the name, confirmed exit). People tab shows a visibility bar and the sources.
- **Setup card "What Bifrost sees in your home"**: per kind (motion, doors, locks/access, phones, Bluetooth, light/buttons, media, air/water, power, calendars, modes, alarm panel, cameras, robots/cars) the number found and what it enables. Recognition by domain, `device_class`, `source_type`, unit, area, floor – never by vendor. New standard sources: `alarm_control_panel` (armed away = strong "empty" label), camera person counts (count > 0 = motion), Bermuda area sensors (room per person), `event.*` button presses.
- **Remove Bifrost's own IRK store** (`/api/irk`, Bluetooth key card): iPhones via HA "Private BLE Device" (key stays in HA) → `device_tracker` with `source_type: bluetooth_le`; rooms via Bermuda (HACS); tags via iBeacon Tracker. Shellys are only Bluetooth proxies. Migration: if keys are stored, show a banner with the steps and a "Delete keys" button; never export keys. Docs (EN/DE) get a "Bluetooth with Shelly" how-to.
- **Pattern chain design (new)**: header card with KPIs, step tiles with icon and share, real connecting lines (fork for OR, join for AND, dashed for companions), groups "OR · one of them", "AND · all, any order", "COMPANION", optional dashed, NOT red, ✓ on done steps of a running routine, sub-patterns expand inline with their own lines. Simple (plain sentences) / Technical (entity → state, spans, shares). Neon accents, light and dark, HA look. The word "level" stays out of the UI.
- Clean-up: remove `patterns.py` (0.3 miner) – its `binary_sensor.bifrost_pattern_*` move to "patterns as entities"; remove `calendars.py` (calendar tab uses calwords); move unused `location.py` parts back to NEXT; remove `s1–s3.png`; structured reasons instead of regex translation for new texts; fix English leftovers in the German UI.
- Stable pattern ids (kept on re-learning with same goal and ≥ 80 % token overlap).

#### 0.8 · Truth instead of self-confirmation
- **Hindsight labeller**: every night the past day is split into certainly empty (confirmed exit → no indoor activity at all → entry), certainly home (indoor activity, modes), unclear. All learning (routines, calendar words, inside/outside, disturbances, durations, signal weights) uses only these labels plus owner labels and answers. `learning.py` trust-from-decisions is removed.
- **Evidence scale**: per signal a learned weight (log-odds), summed and explainable; calibration chart in Balance. The rule engine stays as fallback.
- **Status shows a probability per state**: Home / Asleep / Away with % (sum 100 %), the top state above; "in progress: leaving 60 %" when a chain runs; "Unclear" when no state reaches 70 % or Heimdall blocks, always with the reason. Entities `sensor.bifrost_p_home`, `sensor.bifrost_p_asleep`, `sensor.bifrost_p_away`.
- Realistic simulator (persons without phone, flapping trackers, rooms without sensors, animals) and local backtesting against the stored event history.

#### 0.9 · Control room and house
- **House tab**: per HA floor the HA areas become rooms on a fine grid (36 × 24), first arranged from learned neighbours. The owner picks a room and paints its cells (any shape, e.g. L-shaped hallway), eraser. Neon outline and fill by state: grey quiet / no signal, green motion, orange window/door open, yellow light, magenta media, red unexplained. Label with name, sensor counts, last activity. **One floor plan image per floor** as background (stored locally, max 2 MB, validated). **Person avatars** in the room when a room source (Bermuda) exists. Tap → details: signals with origin, learned paths to neighbours.
- Detectors: baseline per signal × hour of week (rarity in bits → deviation "rare"), path matrix (Markov transitions; impossible jumps and new paths → "contradiction"), routines clustered first (several plans per goal, per person), drift.
- **Incidents** bundle detector hits into one chain: approach → access → inside → identity, score, answers "That was us / Don't know / Unknown".
- Patterns as HA entities (section below), learning-progress card, tabs 11 → 7 (Status · People · House · Patterns · Incidents · Balance · Setup).

#### Tests (all versions)
Guard failure fails closed; guard state survives restart; exit/unknown counting; visibility from `source_type`; IRK migration banner and delete; source catalogue counts; chain rendering (OR/AND/companion lines, expand, simple/technical); hindsight labels on synthetic days; evidence weights and calibration; probabilities sum to 100; cell painting, floor plan validation (type, size); avatars only with a room source; GUI check light/dark/390 px, DE/EN.

### Done in 0.9.0 · Recognised patterns as HA entities (requested 27.11.) – REST entities, MQTT later
Goal: every pattern Bifrost recognises (blocks, people, routines) can be published as its own Home Assistant entity, so owners can use it in their own automations (e.g. "departure in progress" → turn off the heating early, "entry via garage" → light in the hallway).

**Setup**
- New section "Patterns as entities" in Setup: one row per recognised pattern with a switch "Create entity" (default **off**), the entity id that will be used, and the current state.
- Same switch on each pattern card in Pattern recognition (shortcut, same setting).
- Global option `pattern_entities` (on/off) in the app config; off removes all pattern entities.
- Only confirmed patterns can be published (not "suggested" / "not voting yet").

**Entities per pattern type**
- 🔁 Routine → `binary_sensor.bifrost_<slug>`: `on` while the chain is complete (within its window), attributes `progress` (e.g. 3/5), `goal`, `who`, `precision`, `last_seen`, `expected_next` (from timing).
- 🔁 Routine, optional second entity → `sensor.bifrost_<slug>_progress` in % for "arriving soon / leaving soon" automations.
- 🧱 Block entry/exit per door → `binary_sensor.bifrost_<slug>` pulses `on` for a short hold (e.g. 60 s) after a detected entry/exit, attributes `door`, `direction`, `explained`, `who` (person id only if person entities are on).
- 👤 Person → already exists as `sensor.bifrost_person_<slug>`; the switch is shown here too, so all is in one place.
- The existing 0.3 patterns (`binary_sensor.bifrost_pattern_<id>`) move into the same mechanism (migration: enabled → entity on).

**Stable entity ids (important)**
- Today a routine id is a hash of its tokens: a new or replaced sensor changes the id and would break the owner's automations.
- Proposal: when the owner switches the entity on, Bifrost stores a **slug** (default from goal + door/person, editable, `[a-z0-9_]`, unique). When a pattern is re-learned, the new version keeps the slug if it is the same pattern (same goal, ≥ 80 % token overlap – the hygiene rule we already use). If the pattern disappears, the entity becomes `unavailable` with attribute `reason: pattern no longer recognised` and a hint appears in Questions; it is never silently reassigned.

**Limits / decisions needed**
- Entities created via the HA REST API (`set_state`) have no unique_id: not editable in the HA UI and gone after an HA restart until Bifrost publishes again (same as today's entities). Alternative MQTT discovery would give real entities but needs a broker and a client (not stdlib). Proposal: keep REST, document it; MQTT later as an option.
- Safety: pattern entities are information only. They never feed `empty_confirmed` and the docs say clearly: do not use them to disarm.
- Privacy: friendly names may contain person/door names – stay local in HA, never in logs; example data only in docs/tests.
- Budget: max e.g. 30 pattern entities, update only on change (plus every 15 min).

**Open questions for the maintainer**
1. Do blocks (entry/exit per door) get an entity too, or only routines?
2. Pulse (short `on`) or `event` entity style for entries/exits?
3. Progress sensor in % – wanted, or is the attribute enough?

**Tests:** slug stability on re-learning, unavailable when pattern disappears, switch off removes entity, migration of 0.3 patterns, validation of the slug input, UI check (light/dark, 390 px, DE/EN).

### Done in 0.7.0 · Safety fixes from the review (27.11.)
Found in a code review; recommended **before** new features:
1. Guard fail-open: if `brain.tick()` raises, the plain rule decision is used and `guard_ok = all([])` is True → must be Unknown + guard not ok.
2. Guard state (`unknown_min`, last entry/exit, suspicion) is in memory only → persist it; after a restart Unknown – collecting for N minutes (promised in §6.3, not built).
3. Every exit lowers `unknown_min`, also when a known person leaves → only an unexplained exit lowers it.
4. An unmapped access value (`unknown`) counts as a **strong** explanation → weak until the owner maps it; "denied" detection by keywords is fragile.
5. Learned "unreliable" confirms itself (ignored → Away stays stable → fires again → less trust) → labels from independent facts, and a way back.
6. No household defined → people check passes → block `empty_confirmed` in the gate until the household is defined.
7. Smaller: reasons translated by regex on English text (structured reasons would be safer), `service.py` god class, night = hour < 6 fixed, stale engine docstring, old screenshots `s1–s3.png` in the repo root.

### Idea · Learning progress (requested 27.11.)
- Card "Learning progress" at the top of Pattern recognition: learning since, events collected (today/total), last and next learning run, button "Learn now".
- "Almost there": candidates below the thresholds with progress bars – routines (seen x of 5, precision), entrances (openings with direction x of 5), neighbours (count, walking time), people timing (weekdays learned), calendar words (x of 5).
- "Newly detected": patterns that just passed, with date; badge "New" for 7 days in the lists.
- Simple / Technical: Technical shows thresholds and tokens/entity ids.
- Optional entity `sensor.bifrost_learning` (done / in progress).
- Needs: routines.mine and blocks.learn keep candidates instead of discarding them; first-seen date per pattern.


### Idea · Any home, not just ours (review 27.11.)
What homes typically have, and where Bifrost still has gaps:
- **Smart locks** (Nuki, Yale, August, Loxone): who unlocked is often an *attribute* (`changed_by`, user) or an event, not the state. The access system must read attributes and `event.*` entities.
- **Apartments**: one entrance, no outside sensor, a shared staircase. Direction must work with door + inside motion only (motion before = leaving, after = arriving); staircase motion is outside.
- **Camera person detection** (Frigate, UniFi Protect, Reolink): often a *count* (`sensor.*_person_count`) – treat count > 0 like motion instead of dropping numbers.
- **Room presence** (mmWave zones like Aqara FP2, Bermuda/ESPresense BLE): area or zone sensors per person – use as person source with room.
- **Router-only phones** (UniFi, Fritz!Box, without app): flap when iPhones sleep – longer hold time per integration, warn about random MAC addresses.
- **Pets**: pet-immune vs. normal motion; a household setting "we have pets" that lowers trust in floor-level motion at night.
- **Shift work, home office, long holidays, holiday homes**: unknown-reset after 12 h and "away" thresholds per household; holiday mode from calendar.
- **Shared flats / roommates**: several households under one roof – "empty" per household is out of scope; say so in the docs.
- **Minimal homes** (only phones + a few lights): Bifrost must stay useful with phones and power spikes alone and say clearly what it cannot know.
- Onboarding: ask once "house or apartment? pets? alarm system? access system?" and tune defaults and suggestions.


### Done in 0.5.0 · Access events as learned steps (27.11.) – except: smart-lock `event.*` user fields vary by integration, check with real devices
- Every unlock becomes its own event and routine token: `access:<entity>:<user>` (reader + person or "household" for the shared code) – routines learn e.g. "garage gate → NFC garage Person A → cloakroom" even without entry detection.
- Match by user number as well as by name (numeric states from access entities are kept, not dropped).
- Detect "denied / verweigert / invalid / falsch" in the reported value: never an explanation; repeated denials → suspicion / question.
- Smart locks: read `changed_by` / user attributes and `event.*` entities (Nuki, Yale, August, Loxone).
- Per-person count also for unlocks, shared code counted as household.


### Done in 0.6.0 · Remove roles completely (27.11., extends "roles mostly automatic")
- Setup per signal: on/off, category, belongs to. Categories gain "Access" (was role Identity) and split "Modes" into "mode: someone home" (guest/sleep, was Blocker) and "mode: away" (holiday/away). Noise = switched off (robots auto-detected). Trigger = learned entrance or door name; Context/Truth from category.
- Migration: Noise → off, Identity → Access, Blocker → mode: someone home. Role guide removed; optimisations check categories only.

### Done in 0.6.0 · Roles mostly automatic (27.11.)
Today the user picks category **and** role. Since 0.4 Bifrost learns most of what roles express:
- Trigger ⇐ learned entrances (door roles); Noise ⇐ learned trust, origin (automation/timer); Context ⇐ category calendar/weather; Truth ⇐ alarm/lock; Identity ⇐ name/lock.
- Only **Blocker** (guest/sleep mode) is a hard rule the user must decide.
Proposal: the role follows from category + learning; Simple Setup shows only category, "Belongs to" and three switches (counts as activity / prevents "empty" / noise). Technical keeps the role dropdown as override. Engine: Trigger = learned entrance or door to the outside by name.

## 6 · Details

### 6.1 Data and pre-processing
- Sources: all included HA entities (state changes), calendars, device trackers, BLE, later Loxone read-only (individual detectors, alarm state, NFC user) and UniFi.
- **Rising edges only** as events (hold/overrun times ignored); learned **latency and time blur** per sensor; two triggers closer than the blur count as simultaneous.
- **Duplicates** (same detector via Loxone and HA) detected because they always fire together → merged.
- Debounce; unavailable/unknown handled as "no data", never as "off".
- Own event history (raw ~90 days, then counters only), times stored in UTC, windows learned in local time (DST-safe).

### 6.2 Pattern recognition (one engine)
#### 6.2.1 Blocks
- **Entries/exits:** outside motion → door → inside motion = in; inside → door → outside → silence = out. Without an inside sensor near a door the direction is "unknown".
- **Inside vs outside sensors:** fires before a door opens or while the house is confirmed empty → outside.
- **Door profiles:** per door/window and time of day: entries, exits, "opened from inside only" (ventilation, garden) → role suggested ("door B is only opened from inside – garden door?"). Main entrance by real use.
- **Neighbours and walking times:** A then B within seconds, repeatedly → neighbours with walking time; builds the **house map**. Learned without any home/away outcome.
- **Counting:** non-neighbours firing faster than any walk = at least two people (lower bound for the ledger).
- **Garden instead of away:** phone in zone, garden door used last, outdoor/garden activity.
- **Known disturbances:** isolated trigger without entry and without follow-up on neighbours (animals, robot) → disturbance block.
- **Sensor doctor:** dead sensors, chatty sensors, trackers almost never "home", phones with changing Wi-Fi address.
#### 6.2.2 People
- Defined only in the People tab: name (local), sources (tracker, IRK, calendars, NFC user, tag – or none), "may be home alone", type (household / regular visitor).
- **Ledger:** per person home / away / unclear, plus **unknown: at least N** (unexplained entry raises it, exit with silence lowers it).
- A person without any source counts as home until proven away (with an adult who may not leave them alone, schedule + exit, tag).
- **Explanation strength:** NFC strong · companion app with GPS medium · BLE/Wi-Fi weak; at night or at rare doors a weak explanation is not enough.
- Optional entities `sensor.bifrost_person_<slug>`; IRKs stored locally, masked, never logged.
#### 6.2.3 Routines
- Built from blocks and people events with conditions (weekday, time window, calendar words, day type).
- Similar chains are merged into one plan (AND/OR/optional/NOT), timing as spans; longer than 5 steps when the data supports it; rare but informative steps are kept (selection by information value).
- **Early detection:** a partly completed chain already says "arrival in progress" / "departure in progress".
- **Review:** new patterns are suggestions ("not voting yet") with Yes / No / Adjust / Later; "No" suppresses similar ones; drift (Page–Hinkley) asks again.
#### 6.2.4 Pattern hygiene
- Value test (better than its parts, lift / information gain) on top of ≥ 5 observations and ≥ 85 % precision.
- Maximal patterns only; near-duplicates merged; helpers used by only one parent are inlined; shared blocks show "used in N patterns".
- Budget per type and person; patterns not seen for weeks go to the archive.
- **No double counting:** per question only the most specific fully matched pattern counts; types never compete with their parts. Contradicting matches lower confidence → Unknown.
- **Re-evaluation:** when new devices, entities or sources appear (e.g. a new scanner, an IRK) the affected patterns are re-checked: better patterns are suggested, patterns that stop working are flagged. A replaced/renamed sensor is detected ("behaves like the old one") and re-mapping is suggested.
#### 6.2.5 Deviations ("Loki")
- Only **four generic kinds**: expected but missing · happened but unexplained · rare · contradiction (two sources disagree about the same person, door or room).
- **Fast:** event index (event → patterns containing it), expectation list (only patterns whose window is open now), frequency tables for rarity (−log p).
- **Learned negatives:** combinations never seen in N observations become taboo patterns, stronger with N.
- **Fixed contradictions:** indoor motion while confirmed empty without entry; motion in a room not reachable from any entrance; a phone seen via BLE at home while its GPS is far away; an unknown BLE device moving across indoor scanners while nobody is home.
- Messages are generated from the facts involved; the owner can **name** a deviation ("phone forgotten", "animal") and the same structure is recognised next time. Narrow exceptions only (this sensor, isolated, no entry) – never "ignore this sensor"; listed, deletable, re-checked.
#### 6.2.6 Calendar learning 2.0
- Learn every frequently used word (≥ 5) in the chosen calendars; effects: person away · person home · house empty · pattern does not happen · day type.
- Person attribution by names from the People tab; shared family calendars fully usable.
- All-day / multi-day entries = day context; recurring series = plan checked against reality (e.g. "school" during holidays).
- Only words and counters stored; editable block list for sensitive words (never learned, never shown).
#### 6.2.7 Timing
- Arrival/leave times per person and weekday as circular statistics ("usually 17:35 ± 20 min"), durations of states; feeds "arriving soon", `sensor.bifrost_expected_return` and the guard ("somebody is expected – do not suggest arming").

### 6.3 Guard (fixed rules, never learned)
- Recognised entry, indoor motion, sleep mode, guest mode → not empty immediately.
- Empty only if every person is accounted for, unknowns = 0, last-out rule fulfilled (exit through a learned entrance, then no indoor motion for N minutes), data health sufficient.
- After restart: "Unknown – collecting" until the ledger is reliable; learning phase: guard rules and quiet hints only.
- **Suspicious entry:** entry from outside that nothing explains (identity, NFC, guest mode, known routine) with enough strength → level 1 hint (push "was that you?"), level 2 warning (`binary_sensor.bifrost_suspicious_entry` for own automations), later level 3 signal to the alarm system. False-suspicion rate is tracked; the guard gets quieter automatically if it rises and says so.
- Never disarms; complements the alarm system when it is not armed.

### 6.4 Result, questions and UI
- Entities: state, confidence, reason, data health, guest mode, expected return, suspicious entry, open questions; per person optional.
- **Questions:** default recipient is the admin only (configurable); push only for safety, everything else in the Questions inbox (badge, optional weekly digest). Learn first, ask last; ranked by value; grouped; budget (e.g. 1 push/day outside safety, 3 inbox questions/day; modes ask more/normal/little); answers Yes / No / Maybe / Don't know ("Don't know" re-asks only when a similar event happens again, otherwise expires). Every question shows what happened.
- **"That's wrong" button** on the status (and as HA action) – strongest label.
- Tabs: Status · People · House · Pattern recognition (Blocks incl. known disturbances, People, Routines) · Deviations (open / explained) · Calendars · Signals · Questions · Suggestions · Balance · Timeline · Setup. Simple/Technical switch, ⓘ per step, light/dark, phone layout.
- Capability check per house ("direction ✓, people 1/5, guard limited") with missing hardware.
- Profiles cautious / normal / bold; details only in Technical mode. HA blueprints for reactions (later).

### 6.5 Learning and measurement
- Labels: hindsight (entry from outside before indoor motion confirms "empty"; indoor motion without entry refutes it), "That's wrong", push answers ("Maybe" = weak), Loxone alarm/NFC.
- Backtesting of every change against stored history before it may vote; KPIs: false "empty" per month (target 0), share of empty time detected, false suspicions per month, question load.
- Simulator with synthetic households (children without phones, pets, guests, shift work) as release tests.

### 6.6 Operations, privacy, security
- Resource limits (event volume, DB size, nightly incremental mining) shown in Setup; works on small HA hosts.
- Forget/reset per pattern, person, sensor, or everything; Bifrost data is part of HA backups.
- Admin-only app panel; per-person entities optional; retention configurable; export and delete.
- Every update: security check (input validation, permissions, no secrets, dependency and secret scans), tests green, privacy check, checklist.

## 7 · Names and icons
Three parts keep a name, shown as "Name · plain name" with one line icon each:
- **Muninn · pattern recognition** (with **Loki** as its deviation view)
- **Heimdall · guard**
- **Gjallarhorn · result / signal**

Retired as separate experts: Huginn, Verdandi, Skuld, Mímir, Forseti, Frigg, Yggdrasil, Himinbjörg, Ratatoskr – their jobs live inside the three parts.

## 8 · Not planned
- Neural networks (too few labels, no explanation); maybe much later as an optional separate app.
- A separate "second opinion" model – only as a later experiment in shadow mode.
- Patterns built from opinions; automatic disarming; HA persons/users as a requirement.

## 9 · Done
- **0.2** – dashboard, timeline, per-sensor trust, faster setup, own entities.
- **0.4** (not released) – live House tab (HA floors/areas, last path, gaps), who switched it (context + learned timers), slow values as events, language setting DE/EN, live stream, Blocks · People · Routines, People/House/Deviations/Questions/Balance tabs, guard and suspicious entry, calendar 2.0, timing, location groundwork, release gate, one design system DE/EN.
- **0.3** (not released) – patterns as processes (≤ 5 steps, ≥ 5 observations, ≥ 85 %), drift check, calendar keywords, tabs Patterns and Calendars.

### Idea · Learning-progress card (27.11.)
- Show per learner how much data it has: days of history, edges seen, calendar entries compared (needs ~6 weeks), words with ≥ 5 occurrences, patterns found and how often confirmed. So the user sees that Bifrost learns in the background even when nothing is "found" yet.

### Idea · Hint when few signals are used (27.11.)
- If manual activity (lights, buttons) is mostly only "suggested", show one optimisation: "Switch on lights and buttons – they are the best signal that someone is home." Same when motion is only available as aggregated zone sensors.

### Idea · Baseline that says something (27.11.) – waiting for "mach es"
Problem: the card *Baseline per signal* (Patterns → detectors) shows a 7×24 heat map for **one** signal picked from a drop-down. Nobody clicks through 90 signals, and a heat map alone answers no question.

Proposal – turn it around: Bifrost picks what matters, the heat map is only the detail.
- **"Unusual in the last 24 h"** (top of the card): at most 5 rows, sorted by rarity, e.g. *Motion basement · 03:12 · usually never at this hour (0 of 6 Tuesdays)*. Each row: signal, time, plain sentence, rarity as a small neon bar. Empty state: *Nothing unusual in the last 24 h.*
- **"A normal week in your house"**: one heat map for the whole house (all activity signals together, 7×24), with a marker on *now*. Answers "when is somebody usually active?" and shows at a glance what the routines are built on.
- **Detail on tap**: tapping a row (or a cell) opens the per-signal heat map in the existing data popup – no drop-down any more.
- Still learning: *Needs 7 days of data – {n} / 7* instead of an empty map.

Entities / API: no new entities; `/api/patterns` gets `unusual: [{entity_id, ts, rarity, seen, weeks}]` and `house_week: [168 values]` from `baseline.py` (already has `rarity()`).
Limits: rarity needs ≥ 2 weeks per hour slot to be meaningful; below that the row says *too little data*. Energy/air values stay excluded (only activity categories).
Open questions: show the *unusual* list also on Status? Threshold for "unusual" (proposal: rarity ≥ 0.9)?
Tests: unusual list ordering and threshold, house-week aggregation ignores energy/air, empty states; GUI check light/dark/390 px.

### Idea · Bifrost learns what each sensor is good for (27.11.) – waiting for "mach es"
Today `value.py` judges every signal against **one** question: does it tell "home" from "empty"? A window contact then looks useless (opened twice a week), although it is one of the most important sensors against a **break-in**. One verdict per signal is too little – a sensor can be weak for one job and strong for another.

Proposal: a **value per purpose**, learned for every signal, no setting needed.

| Purpose | What it answers | How Bifrost learns it (from data it already has) |
|---|---|---|
| **Presence** | home or empty right now? | evidence weight vs. hindsight, changes per day, hold time (as today) |
| **Patterns** | is it part of routines (leaving, arriving, going to bed)? | how often it appears in learned routines and paths (`routines.py`, path matrix), timing precision |
| **Security** | would it notice an intruder? | position on the shell (`blocks.py`: outside / entrance / inside-next-to-door), it is a door, window, lock or outdoor motion, and how rarely it fires while the house is *certainly empty* (quiet when empty = every trigger counts) |
| **Context** | does it say *when* something will happen? | calendar words, alarm clocks, modes (as today) |

- Every signal gets a small row of verdicts, e.g. *Window living room · Presence: little · Patterns: nothing · Security: **valuable***.
- Suggestions follow the purpose: a signal is only proposed for "off" if it is weak for **every** purpose. Windows stay, even if they say nothing about presence.
- Setup gets a filter per purpose; the Patterns tab shows which sensors carry the routines; the Incidents tab lists the sensors that guard the shell ("these 7 sensors would see an intruder", "back door has no sensor that sees inside").
- Gaps become questions/tips: "Your terrace door has a contact but no motion sensor behind it – an intruder through the terrace would only be seen as 'door opened'."

Limits: security value is a judgement of **coverage**, not a learned intrusion detector – Bifrost never claims to replace the alarm system. Learning needs ≥ 7 days and some hindsight "certainly empty" hours; before that the verdict is "learning".
**Decided (27.11.):**
- Windows are **ignored for presence** (no evidence weight, never "activity right now").
- **Window alarm:** a window on the ground floor or basement (floor level ≤ 0 from the HA floor registry, or set in the House tab) that opens while the house is *empty* or everybody is *asleep* is a **high-severity incident** at once (no waiting, no pattern needed): incident chain "access → window", push message via the notify service, `binary_sensor.bifrost_window_alarm` on. Bifrost only reports – it never arms, disarms or triggers the siren itself; the owner can use the entity in an automation.
- Upper floors: reported as a normal incident, not as an alarm.
Open questions: security coverage as its own card (house outline) or a list? Window alarm also while *leaving* (last person just went out)? Ignore a window that was opened from inside shortly before everybody fell asleep (tilted for the night)?
Tests: window contact = presence little / security valuable; outdoor motion = security valuable; summary zone = presence slow; "off" suggestion only if weak everywhere; GUI check light/dark/390 px.

### Idea · Free patterns – more than arriving, leaving and sleeping (27.11.) – waiting for "mach es"
Today Bifrost only searches patterns **for a goal** (arrival, departure, bedtime): it looks at the hour before each one. Everything else that repeats in the house is not looked for.

Proposal: a second, **goal-free** search over the same facts (edges, block events, person events, energy/water jumps):
- **Recurring sequences** – chains that happen again and again in the same order, e.g. *coffee machine → kitchen light → blinds up* (morning), *TV off → hallway light → bathroom* (evening).
- **Weekly rhythms** – something that happens on fixed days/times, e.g. *cleaner: Tuesday 09:00–12:00, door code + motion everywhere*, *washing machine mostly Saturday*, *children home Wednesday 11:45*.
- **Machines and timers** – things that repeat to the minute without a person (pool pump, robot, timer lights) → marked as "machine", so they never count as activity.
- **Habits that break** – a learned rhythm that does not happen today (*the coffee machine did not run this morning although somebody is home*) or a device left on (*basement light on for 3 h, usually 10 min*).

**Naming without cloud (27.11.)**: Bifrost cannot "understand" a pattern, it only knows facts. The name proposal is built from them: kind + time + rooms + the most telling devices, e.g. *Weekdays 06:40 · kitchen → bathroom · coffee machine*, *Tuesday 09–12 · entrance + motion everywhere*. If a calendar word regularly coincides with it, the word is used (*"Homeoffice"*, *"Ferien"*). Unknown patterns stay neutral (*Pattern 7 · Tue 09–12*) – exactly those may be the ones nobody thought of. The owner renames them once; the name sticks to the pattern's stable id. Optional, opt-in: if Home Assistant has a **local** conversation agent (e.g. Ollama), Bifrost can ask it for a nicer name – the facts never leave the house; without one nothing changes.
Every found pattern gets a plain name proposal, how often it was seen, when, and how precise it is; the owner can rename it, keep it as `binary_sensor.bifrost_<slug>` or hide it. Patterns that predict a state (e.g. "coffee machine = somebody is awake") also feed the evidence scale.
Limits: needs ≥ 2 weeks; at most ~20 proposals, sorted by how often and how regular; energy/water only as jumps.
Open questions: show free patterns in the Patterns tab as their own section ("Everyday life") or mixed with the routines? Push message for "habit broke" (e.g. light left on) – yes/no, or only on the Status page?
Tests: simulator with a weekly cleaner visit, a morning chain and a pool timer → three patterns found with the right kind; machine detection; "habit broke"; GUI check.

### Next version 0.11 · Everyday life, Bluetooth nearby, house map 2.0 (27.11.) – waiting for "mach es"
Decisions of the maintainer (27.11.): free patterns get their own section **"Alltagserkennung" (everyday life)** in the Patterns tab; the HA advertisement monitor is available; Bluetooth positions use the **house map**; the map editor gets better and lets the owner **place Shellys and advertising devices** on it.

**1 · Everyday life – finding patterns cleverly (not "everything")**
Patterns on **three time scales** – long ones (hours) are not too much, they are often the most telling:
- *Sequences* (minutes): chains inside an episode – morning routine, cooking, going to bed (method below).
- *Phases* (hours): every hour is described by a small profile (which rooms are active, which devices used, energy/water jumps, number of phones nearby). Hours that look alike are grouped (clustering); blocks of similar hours that come back are a phase: *home-office 08–17 (office motion, PC power, a coffee every ~2 h)*, *washing day Saturday 09–15 (washer, dryer, basement back and forth)*, *guests' evening 19–23 (dining room, music, more phones than usual)*.
- *Day types* (whole days): days are grouped by their phase sequence – *school day, home-office day, weekend at home, day away, holiday* – and linked with calendar words ("Ferien" → holiday type). Tomorrow's type can be predicted from the calendar.
- *Couplings* (across hours): B regularly follows A with a delay – *dishwasher ~40 min after cooking*, *bathroom 10 min after the alarm clock*, *lights off ~25 min after the TV*.
- *Breaks*: a phase or coupling that should happen today but does not (*no morning routine although it is a school day*), or a device on far longer than in its phase.
Ranking for all scales: how often × how regular × how surprising (lift vs. chance) × size (steps or hours); top 20, grouped by scale.
A fixed "at least 4 steps" would drop good short patterns and still keep noise. Instead Bifrost mines and then *filters by interest*:
- *Episodes*: the event stream is cut into episodes at quiet gaps (≥ 10 min without activity). Patterns are searched inside episodes only.
- *Facts that count as a step*: only person-made changes (origin person/app), block events, person events, energy/water jumps. Not counted: automation/timer changes, the off-edge of the same device, steps that always follow each other by physics or automation (hall motion → hall light within 2 s ≥ 95 %) – they are merged into one step.
- *Closed patterns only*: if "A → B → C → D" is found, its parts "A → B" and "B → C → D" are not shown separately unless they also happen often on their own.
- *Minimum*: ≥ 3 different devices in ≥ 2 rooms **or** ≥ 4 steps; seen on ≥ 5 days.
- *Score* = how often × how regular (time/weekday spread) × lift (happens together far more often than chance) × length bonus. The top 20 are shown, the rest behind "more".
- *Kinds*: daily routine (morning, cooking, evening), weekly rhythm (cleaner Tuesday, washing Saturday), machine (to the minute, no person → marked, never activity), broken habit (expected today but missing, or a device on much longer than usual).
- Each pattern: name proposal, steps as a chain (THEN/AND/OPTIONAL like the routines), when, how often, precision; actions *Rename*, *Keep as entity* (`binary_sensor.bifrost_<slug>`), *Hide*. Patterns that predict a state feed the evidence scale.

**2 · Bluetooth nearby** – as in the Bluetooth concept v2 above (groups, visitors, privacy, fingerprints).

**3 · House map 2.0**
- *Drawing*: rooms as rectangles by dragging (no painting cell by cell); **a room can be several joined rectangles** (L- or T-shaped hallways: select the room, draw another rectangle touching it → it becomes part of the same room, outline drawn as one shape); resize/move by handles, rename and colour; doors and windows as markers on walls; *stairs* as a special room that connects two floors; an *outside* zone (garden, street, drive) around the house; copy a floor as a start for the next one; zoom/pan on the phone; undo/redo.
- *Exact positions*: devices are placed freely (not on grid cells), stored as metres from the floor's corner, with the floor; the grid is only a snap help that can be switched off.
- *Placing devices*: a side list (bottom sheet on the phone) with tabs **Scanners** (Shellys and other Bluetooth proxies from HA), **Bluetooth devices** (from the advertisement monitor, stationary ones first), **Sensors** (motion, doors, windows). Drag onto the map or tap device → tap position. Placed devices show an icon; unplaced ones a hint "3 Shellys not placed yet".
- *Live layer*: Bluetooth positions as soft dots/areas, motion as glowing rooms (as today).
- *Visitors on the map*: an entry through an entrance (door block "entry" without a known phone or code) creates a **visitor token** at that door. It moves along with the next motion events on the learned path matrix (hall → kitchen …) and merges with a Bluetooth device that appeared at the outside scanner just before and now is heard inside ("visitor with a watch"). A named visitor (Post, Cleaner) shows its name. Limits: motion cannot tell two people apart – with several people in the house the token becomes an area ("visitor somewhere on the ground floor"); it disappears with an exit through an entrance or after the guard's unknown-person rules.

**4 · Triangulation across floors**
Floors damp Bluetooth strongly (a concrete slab ~10–20 dB), which helps:
1. *Floor first*: the floor whose scanners hear the device clearly best wins (strongest scanner and the sum of the top 2 per floor). Hysteresis: a floor change needs ~30 s or a stair/motion event on the new floor.
2. *Then the room*: fingerprint match only among the rooms of that floor; with placed scanners also a weighted centre of the strongest scanners of that floor, drawn as an area.
3. *Stairs*: if two floors are almost equal, the device is "on the stairs / between floors" – not guessed.
4. *Calibration*: placed stationary devices (TV, BTHome sensors) give each scanner a per-floor offset; motion in a single room gives fingerprint samples.
Needs ≥ 1 scanner per floor (better 2–3); the floor plan heights are not needed.
*Light construction (timber houses, wooden ceilings)*: a wooden ceiling damps only ~3–6 dB, so "strongest floor wins" is not reliable. Bifrost therefore does not hard-code the damping – it **learns per house** how well floors separate (from placed stationary devices and calibration samples) and picks the method:
- *Floors separate well* (concrete): floor first, then room (as above).
- *Floors separate poorly* (wood): one fingerprint over **all** scanners of the house (3D), so the floor comes out of the whole pattern, not from one scanner; the floor needs a confirmation (motion on that floor, stairs) before it changes; otherwise it says "in the house".
- *Scanner placement hint*: scanners stacked straight above each other cannot tell floors apart – Bifrost suggests offsets ("move the Shelly upper floor towards the other end of the house").
- *Calibration walk* (optional, 5 min): in the House tab the owner walks through the rooms with a known device (phone with the HA app or a placed Bluetooth tag) and taps "I am here" for ~30 s per room – gives clean fingerprints, especially where floors separate poorly.
- Bluetooth also travels further through wooden walls: more neighbours and passers-by are heard, so the "outside" zone and the passer-by filter matter more.

**4b · Map tabs and motion correlation (decided 27.11.)**
- The House map gets three tabs: **Live** (default – family phones with names, visitors, active motion sensors, occupied zones), **Configuration** (place gateways, motion sensors, doors, windows, zones; list of unplaced devices) and **Signal** (accuracy map, start calibrating). Calibration runs from the Signal tab.
- Motion sensors are placed on the map and used for calibration-free learning: a placed motion sensor that fires while a known device is heard gives a sample "device near this sensor / in this room". This is the main way floor changes are learned in a timber house – motion on the upper floor + device heard = sample for the upper floor.
- Tab contents (decided 27.11.): **Live** shows people only (family phones with names, visitors, occupied zones, active rooms) – no gateways, no motion sensors. **Configuration** shows technology only (gateways, motion sensors, Bluetooth devices, doors, windows) – no people. **Signal** draws map and rooms in neutral grey so only the coverage colours stand out.
- **Inside and outside**: the map covers house **and garden**. A *hull* line defines what is inside. *Outside areas* are drawn like rooms (path to the entrance, terrace, seating area, pergola, pool area, driveway …), are marked "outside", never count as "somebody is in the house", but help with arriving/leaving, visitors and calibration. Gateways and motion sensors can be placed outside too; calibration points cover the garden.
- Icons: round, all the same size. Every look must work in light and dark mode.
- **Chosen (27.11.)**: look 1 **"Aurora"** (light and dark) with the round icon set 1 **"Voll"**.
- **Zones** become entities like a motion sensor (`binary_sensor.bifrost_zone_<slug>`, device class occupancy).
- **Per person with IRK**: `sensor.bifrost_<person>_location` – the room, outside area or zone the person is in right now (history comes from HA's recorder). In Bifrost's People tab each such person gets a card with the **last 10 movements** (room → room with time).
- **House shape**: the hull is drawable like a room (several joined rectangles – e.g. an attached garage with its own door), proposed automatically from the outline of all inside rooms and editable.
- **Imported floor plans**: several pictures per floor can be layered; each can be moved, zoomed, rotated and made transparent, so ground floor with garden, upper floor and basement line up over each other (alignment shared across floors via two reference points).
- **All floors at once**: Bifrost shows every floor map one below the other; on a large display side by side as space allows.
- Earlier: round 3 proposals (artifact "Bifrost Kartenstudio 3": 5 looks light+dark × 5 round icon sets) – waiting for the maintainer's choice. Earlier: round 2 proposals (artifact "Bifrost Kartenstudio": 5 looks × 5 icon sets) – waiting for the maintainer's choice.

**5 · Calibration walk ("Einmessen", maintainer's idea 27.11.)** – after the map is drawn and the gateways are placed:
- Button **Calibrate** in the House tab. Bifrost proposes measuring points on the map – about one per 6–10 m², at least one per room, plus near stairs and entrances – floor by floor, shown as numbered dots.
- *Which device is measured* (decided 27.11.: chosen **before the start** from the list of IRK devices of HA's Private BLE Device, preselected: the last one used): the owner picks it once – best a phone that Bifrost can recognise (HA app with BLE transmitter on Android, an iPhone with its IRK in Private BLE Device) or any small Bluetooth tag with a fixed address carried in the hand. Bifrost checks before starting that the device is heard.
- *Measuring*: the owner stands on the shown point, taps **Measure**; Bifrost records 20 s of signal strength from every gateway (median, spread, how many gateways), shows a quality tick (good / weak / heard by < 3 gateways → "add a gateway nearby?") and moves on to the next point. Points can be skipped, repeated, or added by tapping the map.
- *Result*: a radio map per floor (fingerprints at known positions), an estimated accuracy from leave-one-out (*±1.4 m on the ground floor*), coverage gaps marked on the map ("upper floor east: only 1 gateway hears it"). Re-calibrate a single room later.
- *Wooden house*: points on every floor are what makes floors separable at all; Bifrost shows how well each floor separates after the walk.

**5b · "Show signal" – accuracy map after calibrating (maintainer's idea 27.11.)**
- Button **Show signal** in the House tab: a heat map over the floor like a Wi-Fi planner – green = position accurate (± < 1.5 m), yellow = room-level, red = only "in the house" or not heard. Computed from leave-one-out errors of the calibration points, the number of gateways that hear each spot and the wall model in between.
- Tap a red or yellow spot → **Measure here** adds a calibration point at exactly that place; the map updates after each measurement.
- Hints next to the map: "Garage: only 1 gateway – a Shelly near the back door would help"; per floor the share of the area that is accurate.

**5c · Zones on the map that become entities ("phones as motion sensors", maintainer's idea 27.11.)**
- New map tool **Zone**: draw a rectangle (or several joined, like rooms) anywhere – *Sofa*, *Desk*, *Bed parents*, *Front door inside*, *Driveway*. A zone may cross room borders and may lie outside.
- Each zone becomes `binary_sensor.bifrost_zone_<slug>` (device class *occupancy*): on while a tracked device of a family member is inside. Attributes: `people` (names), `devices`, `since`, `accuracy` (expected ± m at this spot). Optional per zone: one entity per person (`binary_sensor.bifrost_zone_sofa_alex`) and a count sensor.
- Usable in automations like any presence sensor – and Bifrost itself uses them as an extra, person-bound motion signal (with its learned value, never alone for "empty").
- Against flapping: enter after ~20 s inside, leave after ~60 s outside (adjustable per zone); a zone smaller than the local accuracy is flagged ("Desk is 1 × 1 m, accuracy here ± 2 m – make it bigger or measure more here").
- Only devices that are bound to a person (phone with HA app / IRK, watch, tag) count; anonymous or visitor devices never switch a zone, named visitors optionally.

**6 · Learning how walls and floors damp the signal (continuous)**
Every placed gateway and every calibration point fits a simple multi-wall model: *strength = transmit power − distance loss − Σ losses of the walls/ceilings crossed*. The rooms on the map give the walls; Bifrost fits one loss per wall type it can tell apart (outer wall, inner wall, ceiling) per house – so it learns e.g. "ceiling 4 dB, inner wall 3 dB" by itself. Afterwards it keeps learning without the owner: whenever exactly one room's motion sensor fires while a known device is heard, that is an extra sample at "somewhere in this room"; samples that contradict the model are dropped. The model fills the gaps between calibration points, the fingerprints stay the reference.

**Limits**: room-level accuracy; rotating phones are only placed while their address lasts (~15 min); everything stays local.
**Decided (27.11.)**: build straight away (no design round), in stages 0.11a map → 0.11b Bluetooth and visitors → 0.11c everyday life. Push for **named** visitors, switchable per visitor. Phones: family phones shown **with the family member's name** (HA app / Private BLE Device), other phones only counted.
**Decided (27.11.)**: calibration is done with the owner's phone resolved by its IRK (HA Private BLE Device).
**Retention, clarified**: rotating addresses (phones without IRK) are never stored per device – only counted per type and dropped after ~15 min. The 14 days apply only to devices with a fixed address (TVs, sensors, tags, watches, car kits, handheld scanners): how long Bifrost keeps one that stopped appearing, unless it was named.
**Decided (27.11.)**: Bluetooth surroundings are recorded **from the update on** (on by default, switch in Setup to turn it off).
**Identification shown per device (decided 27.11.)**:
- *With IRK* (HA Private BLE Device): the device/person name from HA, e.g. "iPhone Alex" – stable, positioned, usable for zones.
- *Without IRK*: the best type Bifrost can read from public data, with how sure it is:
  - Apple (company 0x004C) by message type: *iPhone / iPad / Mac nearby* (Nearby Info – iPhone vs. iPad vs. Watch is a guess and shown as "probably"), *AirPods* (proximity pairing, model readable, e.g. AirPods Pro), *Find My tag* (AirTag or offline device), *Apple TV / HomePod* (AirPlay);
  - Samsung (0x0075) and others mostly by their advertised name ("Galaxy Watch6", "[TV] Samsung 7 Series"); Google Fast Pair (FE2C) → Android earbuds/phone; Microsoft (0x0006) → Windows PC; Garmin, Fitbit, Xiaomi, Tile, BTHome by company id / service uuid;
  - name from the scan response when the Shellys scan actively.
- Always shown: shortened address, address type (fixed / changing), manufacturer, best scanner and signal.
- Rotating devices stay grouped and counted ("3 iPhones nearby"), never followed individually.
**Decided (27.11.)**: fixed-address devices that stopped appearing are deleted after **3 months** (named ones stay). The list shows **only devices present right now**; the positions of **all** of them are drawn directly on the map. Stationary devices (TV, speakers, sensors – learned as "house devices") can be hidden: one switch for all of them plus *Hide* per device; hidden devices still serve as scanner health check and calibration help. Labels as short as possible: "iPhone", "Android", "Watch", "AirPods", "Samsung TV" …; a guess gets a small "≈" mark instead of the word "probably".
**To discuss (reminder set for the maintainer)**: what Bifrost does when it says "everybody away" and a Bluetooth device moves inside the house.
**Status**: 0.11a + 0.11b (map with tabs Live/Configuration/Signal, Aurora look, garden with outside areas, drawable hull, floor plan layers, all floors at once) built in 0.11.0. 0.11c (Bluetooth nearby, calibration, zones, person location) built in **0.13.0**. Still open from the Bluetooth concept: visitor tokens on the map and named visitors with push, signal map from calibration samples (now: gateway estimate + sample dots), learned wall/ceiling damping, calibration-free samples from motion sensors. Next: 0.11d everyday life. Map look: 6 proposals (artifact "Bifrost Kartenwerkstatt") – waiting for the maintainer's choice.
**Tests**: episode cutting and merged automation steps; closed-pattern filter; scoring on a simulated month (morning chain, cleaner Tuesday, pool timer, broken habit); floor decision with hysteresis and stairs; fingerprint room match; editor: rectangles, stairs, device placement saved per floor; GUI check light/dark/390 px.

### Next versions · Entity safety, MQTT Discovery, entity card (27.11.) – waiting for "mach es"
Problem (from the issue): Bifrost writes its entities with `POST /api/states`. If Bifrost stops writing – stop, crash, or an error in `evaluate()` – `binary_sensor.bifrost_empty_confirmed` stays `on` in HA. Checked in the code (0.11.0): nothing writes `off` on stop (`__main__.shutdown` only stops the loop), on an error in the loop (`run_forever` logs and waits) or on start; nothing marks a value as stale.

**1 · Safety: no stale "house empty confirmed" (priority: before every release, in any case before `empty_confirmed` is connected to Loxone)**
Three safeguards that also stay as the fallback without MQTT (proposal – the list was missing in the request):
1. *Fail closed on stop*: SIGTERM/SIGINT → write `empty_confirmed = off` and `house_empty = off` (short timeout) before the process ends.
2. *Fail closed on error and on start*: the first write after start is `off`; any exception in `evaluate()`/`publish()` or an unreachable HA → `off` at the next possible write. A watchdog thread writes `off` if no evaluation succeeded for 3 × the evaluate interval (hung loop).
3. *Freshness for the consumer*: every Bifrost entity carries `updated_at` and `valid_until` (now + 3 × interval); `empty_confirmed` only counts as on while `valid_until` is in the future. DOCS get a ready template / Loxone hint ("arm only if on **and** `valid_until` not passed"). This is the only guard that also covers a hard kill (`kill -9`, power loss) without MQTT.
Tests: stop → off; exception in evaluate → off; start → off first; watchdog → off; attributes present.

**2 · MQTT Discovery (decided: we do it)**
- *Access*: credentials of the Mosquitto broker come automatically from the Supervisor (`GET http://supervisor/services/mqtt`, needs `services: [mqtt:want]` in `config.yaml` – "want", so Bifrost still starts without a broker).
- *Device*: all entities under one device "Bifrost" with a `unique_id` each → renamable, assignable to an area. Existing entity ids are kept (`default_entity_id`), so automations keep working; the old `/api/states` entities disappear after the switch.
- *Classes*: zones as occupancy `binary_sensor`, person location as `sensor`, patterns and zones as `binary_sensor`, state/confidence/probabilities as `sensor` with units.
- *Crash*: `availability_topic` with Last Will `offline` → on a crash all entities become *unavailable* (and `empty_confirmed` is never `on`); additionally `expire_after` for a hung Bifrost.
- *Storage*: states are retained → there right after an HA restart; Bifrost re-sends discovery when HA announces `homeassistant/status = online`.
- *Fallback*: no broker → `/api/states` with the three safeguards from point 1.
- *Implementation*: standard library only – a small MQTT 3.1.1 client: CONNECT (user/password, Last Will), CONNACK, PUBLISH QoS 0/1 with retain, PUBACK, SUBSCRIBE (`homeassistant/status`), PINGREQ/PINGRESP keep-alive, DISCONNECT, reconnect with back-off. No TLS needed (internal Supervisor network).
- *Effort estimate*: client ≈ 300–400 lines, discovery mapping and entity registry ≈ 150–200, tests with an in-process fake broker ≈ 250 – about the size of one stage (like 0.11b). Risks: id migration (old ghost entities), broker restarts, HA versions without `default_entity_id` (fallback `object_id`).

**3 · Setup: card "Bifrost entities" with on/off**
- *List*: every entity Bifrost creates – name, id, kind, current value, last updated, MQTT status (connected / unavailable).
- *On/off per entity*: "off" = Bifrost stops publishing it and removes it cleanly from HA (empty retained discovery config; with `/api/states`: state `unavailable` and no more writes). Internally Bifrost keeps computing it, also for pattern recognition.
- *Safety entities* (`empty_confirmed`, `house_empty`): switching off only after a warning; Bifrost first writes "not empty", then removes them.
- *Filters*: all, on, off, by kind (state, zones, people, patterns, visitors).
- The entity list in the ⓘ info window is replaced by this card.

**4 · Pattern recognition**
- *No loop*: Bifrost's own `bifrost_*` entities stay excluded as input (already the case in the scan – kept and tested).
- *Internal path*: zones and person locations flow into pattern recognition directly inside Bifrost, not via HA.

**Decided (27.11.)**:
- No separate 0.11.1 – the safeguards become part of the MQTT design in **0.12**, which comes **before 0.11c** so the new entities (zones, person locations, visitors) are born as MQTT entities. Order: 0.12 → 0.11c → 0.11d. `empty_confirmed` is not connected to Loxone before 0.12.
- How MQTT covers point 1: a clean stop publishes `offline` itself (the Last Will only fires on a crash); on start Bifrost first publishes `empty_confirmed = off`, then `online` (a retained `on` from before a crash never comes back); a hung loop is caught by `expire_after`; a crash or power loss by the Last Will. The fallback via `/api/states` keeps the three cheap safeguards.
- Entity ids do **not** have to be kept (no automations yet) – clean new ids under the device "Bifrost".
- **Clean-up help**: on the switch Bifrost removes its old `/api/states` entities itself (`DELETE /api/states/<id>`), lists leftovers it cannot remove (e.g. old ids in dashboards) in the new entity card with a "remove" button, and DOCS get a short checklist (what to check in HA after the update).
**Status**: built in **0.12.0** (MQTT client `mqtt.py`, outlet `outlet.py` with safeguards and registry, Setup card, clean-up). Open for later: localised entity names in HA (names follow HA's language).
**Priority (original)**: point 1 before any release. Points 2 and 3 as the next version – proposal **0.12 before 0.11c**, because 0.11c adds many new entities (zones, person locations, visitors) that should be born as MQTT entities right away.
**Open questions**: the three safeguards as proposed? Freshness window 3 × interval (default interval 30 s → 90 s) ok? Keep the existing entity ids under MQTT? 0.12 before 0.11c?
