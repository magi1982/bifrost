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
