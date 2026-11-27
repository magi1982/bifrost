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
Open questions: show the security coverage as its own card (house outline with guarded and unguarded entrances) or only as a list? Should purposes also weigh the evidence scale (e.g. ignore windows for presence completely)?
Tests: window contact = presence little / security valuable; outdoor motion = security valuable; summary zone = presence slow; "off" suggestion only if weak everywhere; GUI check light/dark/390 px.
