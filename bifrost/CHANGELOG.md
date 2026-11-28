# Changelog

All notable changes to Bifrost are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.15.2] – 2026-11-28

### Fixed
- **Changing a floor's size** (e.g. to 11 × 9 m) no longer leaves the rooms off the grid or outside the map: with *Stretch the drawing along* (on by default) rooms, stairs, hull, zones, doors, windows, devices and plan pictures are scaled to the new size, edges rounded to the grid so neighbouring rooms stay joined. Switch it off to only change the size. Calibration points are not moved – calibrate again after a big change.

## [0.15.1] – 2026-11-28

### Changed
- **Areas and sub-tabs look the same**: both rows are neon pills (the area row a little larger); the active one is tinted in the area's colour.
- **Floor plan picture size in %**: 100 % = as wide as the floor's map. The picture grows and shrinks around its **centre** (like turning), with fine buttons −10 % / −1 % / +1 % / +10 % and a field for the percentage; *Left/Top* cover the whole allowed range.
- **All floors at one scale**: 1 m is equally long on every floor map – a ground floor with its garden is drawn larger than a smaller upper floor.

### Fixed
- *Overview* and *Settings* were not marked as the active area.

## [0.15.0] – 2026-11-28

### Changed
- **Navigation with areas and sub-tabs**: six areas at the top – Overview, House, People, Patterns, Safety, Settings – each with its sub-tabs as a row of pills below, in the area's neon colour. Bifrost remembers the last sub-tab per area; every sub-tab has its own address (`#area/sub`), e.g. `#house/signal`. A sub-tab without content says so instead of showing an empty page.
- **Moved**: Bluetooth nearby (with the gateways that send nothing) from Setup to House → Bluetooth; Questions and Balance into Safety; the house map's own Live/Configuration/Signal switch is now the House sub-tabs; Setup is now **Settings**, split into Signals, Bifrost entities, Notifications, Suggestions and Language & maintenance.
- `tools/gui_check.py` checks every area/sub-tab.

## [0.14.0] – 2026-11-28

### Added
- **Everyday life** (Patterns tab): patterns beyond arriving, leaving and sleeping, found in the last 28 days on three time scales – **sequences** (steps in the same order within minutes; automatic follow-ups like motion → light are merged; only the longest chains are kept), **phases** (a room active for hours on weekdays or weekends), **weekly rhythm** (only on one weekday, e.g. cleaning on Tuesday), **couplings** (B follows A by a fixed delay, e.g. dishwasher after cooking) and **timers** (switch on to the minute – never counted as activity). Names are built from the facts (time, rooms, devices); rename or hide each one. **Different from usual today** shows a phase that did not happen or a device on far longer than usual. Random activity produces no patterns (tested); 110,000 events take about a second in the learning run.
- **Bluetooth gateways that send nothing**: Setup → Bluetooth nearby lists the Shellys and ESPHome devices that are not a gateway, with the reason – Bluetooth scanning switched off in HA (with the path), a model without Bluetooth (Gen1, battery devices) or ESPHome without `bluetooth_proxy`.
- API: `/api/everyday` (rename/hide validated: pattern id, name ≤ 60 characters).

### Changed
- **Bluetooth list grouped**: entries with the same identity (e.g. several changing iPhone addresses) form one row with the count and the strongest gateway; *Show all* lists each entry with its own signal strength (dBm and bar) and gateway.
- **Floor plan pictures**: rooms are see-through over a picture (almost invisible while you adjust the picture), the picture turns around its **centre** with buttons ↺/↻ 90°, 1° and 0.1°, *Straight* and *Fit to the floor*; a frame shows the selected picture.
- **Everyday sequences and couplings** use the same chain design as the routines (steps as nodes with "then").

## [0.13.0] – 2026-11-28

### Added
- **Bluetooth nearby** (Setup): everything your Shellys and Bluetooth proxies hear, read from Home Assistant's advertisement stream. Phones with an IRK (HA *Private BLE Device*) show their name, all others a short type (iPhone, AirPods, Android, Samsung TV, BTHome sensor …) – "≈" marks an estimate. Shows present devices only, fixed or changing address, best gateway and signal; hide single devices or all house devices; recording can be switched off. Changing addresses are never stored, fixed ones are forgotten after 3 months without a signal.
- **Positions on the map**: every present device is placed – with calibration by fingerprints over all gateways of the house (works with wooden ceilings), otherwise at the weighted centre of the strongest gateways. Family phones appear with their name where they are.
- **Calibration** (House → Signal → *Start calibration*): pick the IRK phone (or a tag with a fixed address), Bifrost proposes numbered points per room and outside area; stand on the pulsing point, tap *Measure* – 20 s, live signal per gateway, quality, next point. Accuracy per floor (±m) from leave-one-out.
- **Zones** (map tool *Zone*: sofa, desk, bed …): each becomes `binary_sensor.bifrost_zone_<name>` (occupancy) – on while a family phone is inside (20 s in, 60 s out), attribute `people`.
- **Where is everybody**: `sensor.bifrost_<person>_location` (room, outside area or floor) for every person with an IRK phone; the People tab shows the last 10 movements.
- API: `/api/bluetooth`, `/api/calib`, `/api/calib/start`, `/api/calib/delete` (validated: addresses, floors, points inside the floor, sizes).

### Changed
- **House map**: floors without a name ("unassigned") are no longer shown; a floor whose areas are all drawn as outside areas on another floor (e.g. the garden on the ground floor) is shown on that map only.

### Fixed
- **The map no longer stalls.** Floor plan pictures were sent with `no-store`, so the browser loaded every picture again on every redraw (every 5 s and on every mouse move while editing). Pictures now carry a version in their URL and are cached; the live view checks for pictures without reading them; the 5-second refresh pauses while you edit and skips redraws when nothing changed.
- Bifrost's own MQTT entities were reported as "new sensors" – they are now recognised by their unique id and ignored.

## [0.12.0] – 2026-11-27

### Added
- **MQTT Discovery.** With the Mosquitto broker installed, Bifrost publishes all its entities via MQTT under one device **Bifrost** – each with a `unique_id` (renamable, assignable to an area), the right class and unit, retained values (there right after an HA restart) and an availability topic. Credentials come from the Supervisor (`services: mqtt:want`); without a broker Bifrost keeps writing via `/api/states`. MQTT client written with the standard library only.
- **Setup card "Bifrost entities"** – every entity with value, last update and the MQTT status; switch each one **on/off** (off = removed cleanly from HA, Bifrost keeps computing it internally); filters all / on / off / by kind. Replaces the entity list in the ⓘ info window.
- **Clean-up**: once MQTT works, Bifrost removes its old `/api/states` entities itself; leftovers are listed in the card with a remove button.

### Security
- **No stale "house empty confirmed".** On start, on stop, after an error in the evaluation, when Home Assistant is unreachable and when the loop hangs (watchdog), `empty_confirmed` and `house_empty` are written **off** first. With MQTT: a Last Will makes every entity *unavailable* on a crash, a clean stop sends *offline*, and `expire_after` catches a hung Bifrost. Every entity carries `updated_at` and `valid_until`.
- Switching off a safety entity needs a confirmation and writes "not empty" first.

## [0.11.0] – 2026-11-27

### Added
- **House map with three tabs**, all floors shown at once (one below the other, side by side on large screens):
  - **Live** (default) – only people: family members as a phone icon with their name in their room, rooms light up by what happens.
  - **Configuration** – only technology: Bluetooth gateways (blue Bluetooth logo), motion sensors, contacts, Bluetooth devices (white circles), doors and windows; **Edit map** per floor.
  - **Signal** – the map in grey, only the coverage in colour (accurate / room level / rough / weak), estimated from the gateway positions; calibration comes next.
- **Drawing**: rooms as rectangles in metres – several rectangles of one room join into one shape (L- or T-shaped hallways); **outside areas** (path to the entrance, terrace, pool, pergola … – an HA area or a free name) that never count as "in the house"; the **hull** – the outline of the house, drawable too (e.g. an attached garage), by default taken from the rooms; stairs, doors, windows (snap to the nearest wall); select, move, resize, delete, undo/redo, 0.5 m grid, floor size.
- **Place devices exactly**: gateways (Shelly Gen2+, ESPHome proxies from the HA device registry), motion sensors and contacts; unplaced gateways are pointed out.
- **Floor plan pictures**: up to four per floor, each moved, scaled, rotated and made transparent so ground floor with garden, upper floor and basement line up.
- New look "Aurora" in light and dark mode with round icons of the same size. Your 0.9 room layout is taken over automatically.
- API: `/api/map`, `/api/map/reset`, `/api/floorplan` with `layer` (validated: known floor and areas, outside names checked, sizes, at most 240 rectangles, 40 hull rectangles, 240 devices, 4 pictures).

## [0.10.3] – 2026-11-27

### Added
- **New sensors are never overlooked.** Entities that appear after the first scan are highlighted as **New** in Setup (filter *New*, button *Seen*, *Mark all as seen*) and announced on the Status tab.
- **Push message to your phone** when new sensors appear: pick a notify service of Home Assistant (e.g. the Home Assistant app on your iPhone) in the new Setup card *Notifications*, with a test button. Each new sensor is announced once.
- Setup: entities disabled in Home Assistant are hidden by default; the filter *Disabled in HA* shows them.
- Status: card **What Bifrost processes** – events in the last hour and 24 hours, live connection, last and next learning run, how far the evidence scale and hindsight are.
- Calendar words: what was read in the last learning run (entries per calendar, calendars that failed) and words that are almost learned.
- The list of Bifrost's own entities moved from the Status tab into the **ⓘ** info window in the header.
- Status order: *Last 24 hours* now sits right below the state card; *What Bifrost processes* and *Guest mode* moved to the bottom. Data quality and people home moved into *What Bifrost processes* (no more duplicate numbers).
- *May the house be empty?* explains itself: one line per rule, what blocks “empty” right now, and why the rules exist (no wrong “empty” for the alarm signal).

### Fixed
- **A blind left open or a light left on no longer means “home”.** Manual use (lights, blinds, thermostats) counts as *activity right now* only within 5 minutes of the change – before, an open blind could keep Bifrost on “Home” all day while every phone was away.
- The state card no longer shows “Home” and “Unclear” at the same time: below 70 % it now says “Only 66 % sure – below 70 % Bifrost stays careful.”
- **Energy, water and air values are no longer activity.** A power sensor that keeps changing made a room look busy (e.g. a technical room) and kept the house “not empty”. These values now only add context – as jumps they still support patterns – and never light up a room or count as somebody being there.

## [0.10.2] – 2026-11-27

### Fixed
- Setup: an entity that is disabled in Home Assistant but still used by Bifrost (e.g. a phone tracker that UniFi disabled) could not be switched off. Switching off now always works; only switching on stays blocked while the entity is disabled in Home Assistant.
- Setup: switching an entity off made it vanish at once from the list (the filter “All” hides ignored entities), so the switch seemed to do nothing. A row you just switched now stays visible with its new state.
- Tapping a locked switch (entity disabled in Home Assistant, e.g. camera motion that Reolink or UniFi Protect disable by default) now explains why and where to enable it, instead of doing nothing.

## [0.10.1] – 2026-11-27

### Changed
- **“That's wrong” sits right under the state** in the result card on the Status tab. It offers only the states Bifrost did not say (e.g. *Away* and *Asleep* when it says *Home*), then optionally what fooled it.
- States of signals (on, off, open …) are translated in the German UI.
- **Painting rooms is clearer**: every room has its own colour while editing, the room you edit is highlighted (the others dimmed) and named with its number of cells; tools *Paint*, *Erase* and *Pick a room* (tap a room in the plan), *Undo*; rooms not placed yet are marked.
- The “That's wrong” button per person is gone – corrections are made once, on the Status tab.

### Added
- **Data** button at every entity in Setup: a pop-up with the current state, the attributes and the last 24 hours of history from Home Assistant, plus what Bifrost makes of it (category, value, events, weight). Tokens, codes and keys in attributes are never shown.

## [0.10.0] – 2026-11-27

### Added
- **Signal value**: Bifrost judges every used signal by itself – *Valuable*, *Helps a little*, *Brings nothing*, *Slow* or *Still learning* – from what it learned: how well the signal tells home and empty apart (evidence scale), how often it changes, how long it stays on (summary zones from other systems stay on long and are *slow*), duplicates and dead sensors. The verdict and its reason are shown at every entity in Setup.
- Setup filters **Brings nothing** and **Slow** with counts; “What Bifrost sees” also counts the valuable signals per kind.
- Optimisation “Brings nothing – switch off?” / “Slow – switch off?”. Bifrost only suggests; you decide.
- House tab: signals that bring nothing or are slow are archived – hidden from rooms, the lane and the area cards; **Show archived** brings them back.

## [0.9.1] – 2026-11-27

### Added
- **What is happening right now** (House tab): the last hour as a lane per area – every event a dot, detected entries and exits as lines, events triggered by an automation or a schedule hollow.

### Removed
- The old 0.3 pattern view, the timeline and dashboard views with their APIs (`/api/timeline`, `/api/dashboard`, `/api/deviations`) and the old pattern-chain styles – about 30 KB less in the UI.

## [0.9.0] – 2026-11-27

### Added
- **House: rooms on your floor plan.** Per Home Assistant floor every area is a room on a fine grid. Bifrost suggests a first layout (rooms people walk between sit next to each other); you pick a room and paint its cells – any shape, also L-shaped or slanted. Each room is coloured by what happens: grey quiet/no signal, green motion, orange window/door open, yellow light, magenta media. **One floor plan picture per floor** can lie underneath (PNG/JPEG, max. 2 MB, stored locally).
- **People in their room** when a room source (e.g. Bermuda) is clear and steady for 2 minutes – otherwise shown as “in the house”.
- **Incidents** (tab *Incidents*): deviations that belong together are bundled into one chain – approach → access → inside → identity – with a score, and can be answered right there.
- **Two more detectors**: a **baseline** per signal and hour of the week (a firing at an hour where it never fires becomes the deviation *rare*) and a **path matrix** between areas; indoor motion while the house is empty without any door becomes a *contradiction*.
- **Routines per habit**: departures, arrivals and bedtimes are grouped by time of day and working day/weekend first, so one goal can have several plans (e.g. work in the morning, shopping at noon); the same habit on other days is merged.
- **Patterns as entities**: switch single patterns on as `binary_sensor.bifrost_<slug>` for your own automations (routines on when complete, entry/exit as a short pulse). The slug survives re-learning; a pattern that disappears becomes *unavailable*. Information only – never used for “house empty confirmed”.
- **Learning progress** card on the patterns tab: what is learned, what is almost there, newly found patterns, “Learn now”.

### Changed
- **7 tabs instead of 11**: Status · People · House · Patterns (with calendar words and the detectors) · Incidents (deviations and questions) · Balance · Setup. Timeline and dashboard are gone; the last 24 hours stay on Status.

## [0.8.0] – 2026-11-27

### Changed
- **Bifrost learns from hindsight, not from itself.** Every few hours it looks back and splits the history into *certainly empty* (confirmed exit → quiet → entry, alarm “armed away”), *certainly home* (activity inside; quiet after which activity resumes without anybody coming in – e.g. a child without a phone upstairs) and *unclear*. Routines, calendar words, inside/outside, disturbances and departures learn only from this and from your corrections – never from Bifrost's own live decision.
- **Evidence scale instead of hand-made confidence.** Every signal gets a learned weight (how much more often it fires when somebody is home than when the house is empty). The live estimate is the sum of what is true right now – explainable on the Status tab. It may only make Bifrost more careful: below 70 % “empty” it says *Unknown*; it never turns a rule decision into “empty”.
- Signals that fire as often when the house is empty (animals, robots, drafts) are no longer counted as activity – learned from hindsight instead of the old trust score. “That's wrong – this fooled Bifrost” makes a signal count less on the scale.
- The release gate counts departures confirmed in hindsight, and **“empty” while somebody was certainly inside counts as a wrong “empty”** like an owner's correction.

### Added
- **Status shows a percentage for every state**: Home, Asleep and Away (together 100 %), the current decision above, “in progress” when a routine runs, and how Bifrost calculated it.
- Entities `sensor.bifrost_p_home`, `sensor.bifrost_p_asleep`, `sensor.bifrost_p_away`.
- **Balance**: hindsight summary (hours certainly home / empty / unclear, departures, wrong “empty” in hindsight) and a calibration chart – when Bifrost said “x % empty”, how often was it really empty.
- **Backtesting on your own data**: `tools/backtest.py` runs the hindsight labeller over a copy of your database locally and compares it with Bifrost's past decisions.
- Realistic simulator: a child without a phone who stays upstairs, a flapping Wi-Fi tracker, animals.

### Removed
- The trust learner that judged signals by Bifrost's own decisions.

## [0.7.0] – 2026-11-27

### Security
- **Heimdall fails closed.** If the safety check itself fails, Bifrost never says “empty” and `binary_sensor.bifrost_empty_confirmed` stays off.
- **The guard survives restarts.** Unknown people, the last entry and exit and an open suspicion are saved. For 10 minutes after a start Bifrost collects before it may say “empty”.
- **An exit needs proof.** Quiet after a door is no longer an exit – every house has rooms without sensors. An exit needs an outside sensor right after the door or a phone leaving; otherwise it is “door used, direction open”.
- Only an exit that no known person explains lowers the “unknown people” counter.
- An access value nobody assigned counts as a medium explanation (enough by day, not at night) instead of a strong one.
- “That's wrong” on a wrong “empty” marks somebody unknown inside until a confirmed exit.
- The release gate for the alarm signal also needs at least one person in the household.

### Added
- **Visibility per person** (well / partly / invisible), worked out from the assigned sources with the Home Assistant standard `source_type` instead of a list of integration names.
- **Setup card “What Bifrost sees in your home”**: per kind of signal how many entities exist and what they enable – recognised by Home Assistant standards, never by vendor. Alarm panels, Bluetooth trackers, Bermuda area sensors and camera person counts are recognised.
- **Bluetooth help in Setup**: Shellys as Bluetooth proxies, iPhones via *Private BLE Device*, rooms via *Bermuda*. Bermuda area sensors can belong to a person.
- **New pattern chain**: steps as tiles with real connecting lines – a fork for OR, a join for AND, dashed lines for companions; sub-patterns open inline with their own lines; Simple (plain sentences) and Technical (entity → state, time spans, shares). Neon accents in light and dark.
- Pattern ids stay the same when a pattern is re-learned with the same goal and mostly the same steps.

### Changed
- **Bluetooth keys (IRK) are no longer stored in Bifrost.** They belong in Home Assistant (*Private BLE Device*). Keys stored by older versions are listed masked with a button to delete them.
- The calendar tab shows the learned calendar words and what they mean.
- Pattern titles and steps are translated (no more English in the German UI).

### Removed
- The 0.3 pattern miner (replaced by routines) with its `binary_sensor.bifrost_pattern_*` entities, the 0.3 calendar learner (replaced by calendar words) and unused Bluetooth-fingerprint / CO₂ code.

## [0.6.0] – 2026-11-27

### Changed
- **Roles are gone.** In Setup you only choose on/off, the category and – for phones and calendars – who it belongs to. Bifrost derives by itself how a signal counts, from the category, the name and what it learned (e.g. which door is really an entrance).
  - New categories **Mode: someone home** (guest, sleep, night – “empty” is impossible while on), **Mode: away** (holiday/away – a clue for empty) and **Access** (keypad, NFC, fingerprint, “last user”). The old “Modes” category is split into the two modes.
  - Signals you had set to “Noise” are switched off; old roles are migrated automatically on the next scan.
  - The guide in Setup now explains the categories (“Which category for what?”).
  - Optimisations only suggest on/off and category.
- **Better filters in Setup**: status and category chips with counts, floor, area, integration and kind, “No area”, “No ‘Belongs to’”, “With optimisation”, sorting and a reset button. Filters are remembered in the browser.

### Fixed
- The optimisation card closed too early, so the second suggestion appeared outside the card.

## [0.5.3] – 2026-11-27

### Changed
- **“That's wrong” now teaches something and sits where you need it** – right under the result on the Status tab, and per person in the People tab.
  - Whole house: pick what is really true. A wrong “empty” or a wrong “home” counts in the balance (a wrong “empty” blocks the alarm signal).
  - Then optionally tap **what fooled Bifrost** from the signals that changed in the last 30 minutes: that signal loses trust; a motion sensor that fired while nobody was home also gets the question “animal or disturbance?”.
  - Per person: “home” or “away”. The person's phones that said otherwise lose reliability; after three mistakes they only count as a weak source.
  - Bifrost tells you after each correction what it learned.

### Fixed
- Corrections made in the same instant overwrote each other.
- The suspicious-entry banner showed the entity id instead of its name.

## [0.5.2] – 2026-11-27

### Fixed
- Setup: entity ids, areas and integrations were cut off with “…”; the full text now wraps.
- Setup: calendars, phones and trackers that were only *suggested* had no “Belongs to” dropdown. It now shows for every such entity, and assigning it to a person or the household switches it on.

### Added
- Setup shows **who disabled** an entity in Home Assistant (its integration, you, its device or the integration itself) and where to enable it again. UniFi, for example, disables trackers of devices that were offline during setup.
- Teslas are recognised by their Bluetooth name (“S” + 16 hex characters + “C”) as a car near the house.

### Changed
- Vehicles have no “Belongs to”: a car at home does not mean its driver is home. The pattern recognition learns “car comes home → person comes home” by itself.

## [0.5.1] – 2026-11-27

### Security
- **Own AppArmor profile** (`apparmor.txt`): based on Docker's default container profile, plus restrictions Bifrost never needs – no raw or packet sockets, no mounts, its own code is read-only at runtime, no access to SSH keys, `/ssl` or writes to `/share`. Raises the Home Assistant security rating from 7 to 8 (the maximum) once the app is installed.

## [0.5.0] – 2026-11-27

### Changed
- **One place for every source: Setup.** Setup says *what* a signal is and *who it belongs to*; the People tab only holds the name, the kind (household / regular visitor) and “may be home alone”, plus a read-only overview of each person's sources.
  - Phones, trackers and calendars get a **“Belongs to”** dropdown right at the entity; calendars can belong to the **whole household**.
  - New role **“Identity”** for entities that report *who* it was (keypad, NFC, fingerprint, “last user” sensors). The scanner suggests it from the name; Optimisations point it out; the role guide explains it.
  - Every reported user or **user number** is listed under its entity and assigned to a person, marked as **household code**, ignored – or left unassigned, which still counts as “someone authorised”.
  - **Bluetooth keys (iPhone IRK)** have their own card in Setup with label and owner; keys are never shown again.
- Existing data is migrated automatically (NFC user → access users, IRK on the person → Setup key, access entities from 0.4.1 → role Identity).

### Added
- **Smart locks** (Nuki, Yale, August, …): when a lock unlocks, Bifrost reads who did it from the lock's attributes (`changed_by`, user). Locking stays an ordinary signal.
- **Unlocks are learned steps**: every unlock becomes its own event with reader and person (or “household” / “authorised”), so routines learn e.g. “garage gate → keypad garage · person → cloakroom” even without entry detection. Unlock counts per person in the People tab.
- **Access denied** (“denied”, “verweigert”, “invalid”, …) is never an explanation; it is recorded as an unexplained deviation.

### Security
- Only a fixed list of lock attributes is read (and cut to 40 characters); everything else from the event is dropped. All new endpoints validate entity ids, person ids, values and keys.

## [0.4.2] – 2026-11-27

### Added
- **Setup → Optimisations** – Bifrost checks every scanned signal against what works best and suggests one change per entity, each applied or hidden on its own (no “apply all”): doors to the outside → Trigger, windows → Evidence, floor-length windows and sliding doors to garden or terrace → Trigger if people walk through them, motion sensors switched off → on, guest and sleep modes → Blocker, robots → Noise, alarm → Truth, calendars → Context, signals disabled in Home Assistant or found by the sensor doctor → off. Once Bifrost has learned how a door is used (entrance or only opened from inside), that wins over the name.

### Fixed
- Door contacts that Home Assistant lists with the device class “window” (very common) were never treated as doors when learning entrances. The name now wins: “front door”, “Haustüre”, “Garagentor”, sliding doors and floor-length windows to the garden or terrace are learned as possible entrances; the scanner suggests them as Trigger right away.

## [0.4.1] – 2026-11-27

### Changed
- **People** – phones, trackers and calendars are picked from a dropdown and shown as chips, instead of a long list of all entities.
- **Access system instead of “NFC at the keypad”** – optional and generic (keypad code, NFC, fingerprint). Pick the entity that reports who unlocked; Bifrost lists the users it has seen and you assign them to a person in a dropdown – no typing. A user can belong to only one person. Matching is by whole word.
- **Shared household code** – a code the whole family uses can be marked as shared: it explains an entry (“somebody from the household”) without being assigned to a person.
- **Setup** – new guide “Which role for what?” with the meaning of every role and a recommendation per signal type. The **Signals** tab is gone (it showed the same as Setup), and so is the “Use all suggestions” button.

### Fixed
- In Setup some switches jumped back after the German translation: the role dropdown sent the translated name. Dropdowns now always send the internal value; switching on a signal without a category asks for one first.
- Category names in Setup dropdowns were still English.

## [0.4.0] – 2026-11-27

### Added
- **Live event stream** – Bifrost subscribes to state changes over the Home Assistant WebSocket API and keeps the exact time and order of every used sensor (short door openings included). Edges are debounced, unavailable states count as gaps, duplicate sensors are detected. Option `event_stream` (on).
- **Pattern recognition** – one tab with three pattern types, learned automatically for any house:
  - **Blocks** – neighbouring sensors and walking times (house map), inside/outside sensors, entrances with direction, door roles (entrance / opened from inside only), known disturbances, sensor doctor and a capability check.
  - **People** – how each person comes home, built from their sources.
  - **Routines** – chains with THEN / AND / OR / optional / NOT steps, companions, weekday, time and calendar-word conditions, precision replay, value test, merge and budget against pattern sprawl, live progress.
- **People tab** – people live only in Bifrost (no Home Assistant users). Per person: trackers, calendars, NFC user, iPhone IRK (masked, never returned), “may be home alone”. Unknown people are counted as “at least N”.
- **Guard** – fixed safety rules for “may the house be empty?” (fresh entry, everybody accounted for, no unknown people, last one out, data health) and **suspicious entry** detection; at night a weak explanation (Bluetooth/Wi-Fi) is not enough. Option `suspicious_entry_level` (2).
- **Deviations and Questions** – expected-but-missing, unexplained, rare and contradicting events; questions and suggestions with a daily budget (3/5), safety first, grouped, answered Yes / No / Maybe / Don't know, optional labels, expiry after 7 days, known exceptions.
- **House tab (live)** – floors and areas from Home Assistant as tiles; every used signal with its last change, refreshed every 5 seconds. Areas that are active right now light up. Shows the last path through the house (e.g. garage → garage door → cloakroom → hallway), people at home, and gaps (door without sensor, area without signal, signal without area, sensor doctor). Simple / Technical switch: Technical adds entity ids, states, origin, learned neighbours with walking times, entrances, exceptions and the optional floor plan (PNG/JPEG, max 2 MB).
- **Who switched it?** – Bifrost reads the Home Assistant context of every change: by hand (device), via app (user) or by an automation (parent). Lights, blinds or media switched by an automation – or by a timer Bifrost learned (same time on 5 of the last 14 days, e.g. a Loxone timer) – no longer count as a person.
- **Slow values as events** – humidity jump (shower), CO₂ rise, power spike above base load and water flow become events for the live view and the pattern recognition; trends are shown next to the value.
- **Language setting** – German or English for the whole app and the texts in the Bifrost entities. On first start Bifrost uses the Home Assistant language; switch it any time in Setup.
- **Calendar learning 2.0** – all words (≥ 5 occurrences) are learned with their effect (house empty, per person, day type, missing routines); a block list keeps sensitive words out; full titles are never stored.
- **Timing and location** – typical arrival/departure per person and weekday; BLE fingerprint and access point place as groundwork for ESP32 scanners.
- **Balance tab** – key figures and a release gate. `binary_sensor.bifrost_empty_confirmed` only turns on with option `alarm_signal` (off) and a green gate (30 days, ≥ 20 departures, 0 wrong “empty”, health ≥ 90 %). Bifrost never disarms.
- **“That's wrong”** correction on the Status tab (home / away / asleep) stored as a label.
- New entities: `binary_sensor.bifrost_suspicious_entry`, `binary_sensor.bifrost_empty_confirmed`, `sensor.bifrost_open_questions`, `sensor.bifrost_unknown_people`, `sensor.bifrost_person_<id>` (option `person_entities`).
- One design system for the whole app (icons, buttons, chips, cards, Simple / Technical switch) in light and dark.
- `tools/demo_server.py` and `tools/gui_check.py` – demo household with example data and an automated GUI check (text overflow, squeezed columns, clickable buttons, JavaScript errors, English text left in the German UI) in light, dark and phone width.

### Changed
- The **Patterns** tab is replaced by **Pattern recognition**.
- Events are stored with a kind and in UTC; a generic object store holds the learned model.

### Security
- The Home Assistant context is only read to tell person, app and automation apart; user ids are never stored.
- New write endpoints require the `X-Bifrost-Request` header and JSON, every field is validated (length, format); the floor plan has its own 3 MB body limit and is checked for PNG/JPEG signatures. IRKs are never logged, exported or sent to the browser.

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
