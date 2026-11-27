# Bifrost

**Local, explainable presence detection for Home Assistant.**
*Is anybody home?* Bifrost combines all the signals your home already has – phones, motion, doors, windows, modes, media, calendars – into one clear answer with a confidence and the reasons behind it.

> ⚠️ **Experimental (v0.10).** Bifrost runs in *shadow mode*: it observes, learns and explains. The only signal it can ever give your alarm is “house empty confirmed” – and only after you switch it on and the balance has been green for 30 days. Bifrost never disarms anything.

[🇬🇧 English](#english) · [🇩🇪 Deutsch](#deutsch)

---

## English

### What Bifrost does
1. **Scans** your Home Assistant: every entity, device and area – including disabled and unavailable ones.
2. **Sorts** every entity into one of 14 categories (Motion, Doors & windows, Manual use, People & devices, Network, Media, Climate, Energy, Vehicles & tags, Mode: someone home, Mode: away, Calendar, Security, Access). You only decide **on/off**, the **category** and, for phones and calendars, who it **belongs to**. There are no roles to set: Bifrost derives by itself how a signal counts – from the category, the name and what it learned (for example which door is really an entrance). A switched-off signal is simply not used.

3. **Decides**: Home · Asleep · Leaving · Away · Arriving · Unknown – with a confidence (0–100 %) and plain-language reasons.
4. **Publishes** the result as entities you can use anywhere:

   | Entity | Content |
   |---|---|
   | `sensor.bifrost_home_status` | home / asleep / leaving / away / arriving / unknown |
   | `binary_sensor.bifrost_house_empty` | `on` when the house is empty |
   | `sensor.bifrost_confidence` | confidence in % |
   | `sensor.bifrost_reason` | main reason (all reasons as attribute) |
   | `sensor.bifrost_data_health` | share of selected signals that are available |
   | `sensor.bifrost_expected_return` | typical return time on this weekday (learned) |
   | `binary_sensor.bifrost_anomaly` | `on` when there is activity while every tracked phone is away |
   | `binary_sensor.bifrost_guest_mode` | Bifrost guest mode |
   | `sensor.bifrost_person_*` | home / away per person |

5. **Learns** how reliable every sensor is. A sensor that keeps firing while the house is confirmed empty (a pet, a robot, a draft) stops counting as activity.

### How Bifrost thinks (since 0.4)
Bifrost listens live to every used sensor (exact time and order, short door openings included) and works in three parts:

| Part | Question | What it does |
|---|---|---|
| **Pattern recognition** | *What is normal here?* | Learns by itself, for any house: **Blocks** (which sensors are neighbours, which are inside or outside, which doors are entrances and from which side they are opened), **People** (who comes home how – phone, NFC code, Bluetooth key) and **Routines** (recurring chains like *garage door → cloakroom → phone home*, with AND / OR / optional steps, companions, weekdays, times and calendar words). Anything that does not fit lands in **Deviations**. |
| **Guard** | *May the house be empty?* | Fixed safety rules: after an entry the house stays “not empty” for 15 minutes; “empty” needs every person away, no unknown people inside, the last one out detected and healthy data. A door opened from outside while everybody is away or asleep, with no explanation, is a **suspicious entry**. |
| **Result** | *What does Home Assistant get?* | The decision, the reasons and the entities below. |

**Learning from hindsight (since 0.8).** Bifrost never learns from its own live decision. Every few hours it looks back: a quiet stretch between a confirmed exit and an entry was *certainly empty*; activity inside – or a quiet stretch after which activity resumes without anybody coming in – was *certainly home*; the rest is *unclear* and not used. From this it learns an **evidence scale** – one weight per signal – and shows a **percentage for every state** (Home, Asleep, Away). The scale can only make Bifrost more careful. `tools/backtest.py` runs the same hindsight over a copy of your database and shows how often Bifrost said “empty” while somebody was inside.

**People live only in Bifrost** – no Home Assistant users are needed. The People tab holds only names, the kind (household or regular visitor) and “may be home alone”. Everything technical is assigned in **Setup**, right at the entity: phones, trackers and calendars get a “Belongs to” dropdown (calendars can belong to the whole household); entities in the category **Access** (keypad, NFC, fingerprint, “last user”) and smart locks list the users they reported, which you assign to a person, mark as household code or ignore – unassigned unlocks still count as “someone authorised”. iPhone Bluetooth keys (IRK) live in Home Assistant (**Private BLE Device**); Bifrost reads the trackers – see the Bluetooth help card in Setup. From the assigned sources Bifrost works out how **visible** each person is (well / partly / invisible, using the HA standard `source_type`). Children without phones are welcome: they count as home until facts say otherwise, and entries Bifrost cannot explain count as “unknown – at least N”.

**Questions instead of guessing.** When Bifrost is unsure it asks – at most 3 questions and 5 suggestions a day, safety first. You answer *Yes / No / Maybe / Don't know* and can name the reason (“animals”, “cleaner”). Answers become known exceptions; “don't know” is asked again later.

**Who switched it?** Bifrost reads the Home Assistant context of every change. A light switched by an automation – or by a timer it learned, e.g. one in Loxone – is not a person. Humidity jumps, CO₂ rises and power spikes count as events too.

**Language.** German or English, set in Setup. On first start Bifrost uses the Home Assistant language.

**Balance.** Bifrost keeps score: wrong “empty”, detected empty time, suspicions and false alarms. The `alarm_signal` option only takes effect once the release gate is green (30 days in shadow mode, 20 detected departures, 0 wrong “empty”, data health ≥ 90 %, at least one person in the household).

New entities: `binary_sensor.bifrost_suspicious_entry`, `binary_sensor.bifrost_empty_confirmed` (only with `alarm_signal`), `sensor.bifrost_open_questions`, `sensor.bifrost_unknown_people`, `sensor.bifrost_person_<id>`.

### Tabs
| Tab | What you see |
|---|---|
| **Status** | Current result with a percentage for Home, Asleep and Away, reasons, “That's wrong”, “May the house be empty?” checklist, people, suspicious entry, guest mode, last 24 hours |
| **People** | Names, kind, “may be home alone” and how visible each person is from their sources; unknown people inside |
| **House** | Rooms per floor on a grid over your own floor plan, coloured by what happens, people in their room; live signals, last path, gaps. *Technical* adds entity ids, origin, learned connections and entrances |
| **Patterns** | Learning progress; Blocks · People · Routines as chains with lines (OR / AND / companions, sub-patterns open inline, Simple / Technical); switch a pattern on as an entity; detectors (baseline per signal, paths between areas); calendar words |
| **Incidents** | What did not fit, bundled into chains (approach → access → inside → identity) with a score; questions and suggestions – Yes / No / Maybe / Don't know |
| **Balance** | Key figures, hindsight, “are the percentages right?” and the release gate for the alarm signal |
| **Setup** | Language, “What Bifrost sees in your home”, value per signal (valuable / brings nothing / slow) with filters, guide, optimisations, Bluetooth help, filters, scanner and configurator for all entities incl. “Belongs to” and reported users |

### Installation
1. In Home Assistant open **Settings → Apps → App store → ⋮ → Repositories**.
2. Add `https://github.com/magi1982/bifrost`.
3. Install **Bifrost**, start it and open it from the sidebar.
4. Go to **Setup** and look at the suggestions. Switch on what Bifrost may use, correct wrong guesses. That's it.

### Options
| Option | Default | Description |
|---|---|---|
| `update_interval` | 30 s | How often Bifrost re-evaluates |
| `phone_away_minutes` | 10 | How long all phones must be away before "Away" |
| `no_motion_minutes` | 15 | How long without activity before "Away" |
| `shadow_mode` | on | Only observe – never trigger anything |
| `publish_entities` | on | Create the `bifrost_*` entities |
| `use_learning` | on | Learn how reliable each sensor is and ignore sensors that fire while nobody is home |
| `learn_calendars` | on | Learn which calendar entries mean nobody is home (keywords only, titles are never stored) |
| `event_stream` | on | Listen live to sensor changes (exact time and order) |
| `suspicious_entry_level` | 2 | 0 = off, 1 = report in the app, 2 = also turn on `binary_sensor.bifrost_suspicious_entry` |
| `person_entities` | on | One `sensor.bifrost_person_<id>` per person |
| `alarm_signal` | off | Allow `binary_sensor.bifrost_empty_confirmed` once the balance is green. Never disarms. |
| `log_level` | info | Logging detail |

### Privacy & security
Everything stays in your home. No cloud, no telemetry, no dependencies outside the Python standard library. The UI is only reachable through Home Assistant (Ingress), and the app runs with its own AppArmor profile (security rating 8 of 8). See [SECURITY.md](SECURITY.md).

### Roadmap
Backtests on real data and the release gate on real data, then the signal to the alarm system (1.0). Loxone read-only connector for alarm state and NFC users. See [NEXT.md](NEXT.md).

---

## Deutsch

### Was Bifrost macht
1. **Scannt** dein Home Assistant: alle Entitäten, Geräte und Bereiche – auch deaktivierte und nicht verfügbare.
2. **Sortiert** jede Entität in eine von 14 Kategorien (Bewegung, Türen & Fenster, Manuelle Bedienung, Personen & Geräte, Netzwerk, Medien, Klima, Energie, Fahrzeuge & Tags, Modus: jemand daheim, Modus: abwesend, Kalender, Sicherheit, Zutritt). Du entscheidest nur **ein/aus**, die **Kategorie** und bei Handys und Kalendern, wem sie **gehören**. Rollen gibt es nicht mehr: Bifrost leitet selbst ab, wie ein Signal zählt – aus Kategorie, Name und Gelerntem (z. B. welche Tür wirklich ein Eingang ist). Ein ausgeschaltetes Signal wird einfach nicht genutzt.

3. **Entscheidet**: Home · Asleep · Leaving · Away · Arriving · Unknown – mit Sicherheit in Prozent und verständlichen Gründen.
4. **Stellt das Ergebnis als Entitäten bereit**, die du in eigenen Automationen und Dashboards nutzen kannst (Tabelle oben).
5. **Lernt**, wie zuverlässig jeder Sensor ist. Ein Sensor, der immer wieder auslöst, während das Haus nachweislich leer ist (Haustier, Saugroboter, Durchzug), zählt nicht mehr als Aktivität.

### Wie Bifrost denkt (ab 0.4)
Bifrost hört live auf jeden genutzten Sensor (genaue Uhrzeit und Reihenfolge, auch kurze Türöffnungen) und arbeitet in drei Teilen:

| Teil | Frage | Was er tut |
|---|---|---|
| **Mustererkennung** | *Was ist hier normal?* | Lernt selbst, in jedem Haus: **Bausteine** (welche Sensoren Nachbarn sind, was innen und aussen ist, welche Türen Eingänge sind und von welcher Seite sie geöffnet werden), **Personen** (wer wie heimkommt – Handy, NFC-Code, Bluetooth-Schlüssel) und **Abläufe** (wiederkehrende Ketten wie *Garagentor → Garderobe → Handy daheim*, mit UND / ODER / optionalen Schritten, Begleitern, Wochentagen, Uhrzeiten und Kalenderwörtern). Was nicht passt, landet in **Abweichungen**. |
| **Wächter** | *Darf das Haus leer sein?* | Feste Sicherheitsregeln: Nach einem Eintritt bleibt das Haus 15 Minuten „nicht leer“; „leer“ braucht alle Personen weg, keine Unbekannten im Haus, erkannten letzten Rausgehenden und gesunde Daten. Eine Tür, die von aussen geöffnet wird, während alle weg sind oder schlafen, ohne Erklärung, ist ein **verdächtiger Eintritt**. |
| **Ergebnis** | *Was bekommt Home Assistant?* | Die Entscheidung, die Gründe und die Entitäten unten. |

**Lernen aus dem Rückblick (ab 0.8).** Bifrost lernt nie aus der eigenen Live-Entscheidung. Alle paar Stunden schaut es zurück: Ruhe zwischen bestätigtem Austritt und Eintritt war *sicher leer*; Aktivität drinnen – oder Ruhe, nach der es drinnen weitergeht, ohne dass jemand hereinkam – war *sicher daheim*; der Rest ist *unklar* und wird nicht genutzt. Daraus lernt es eine **Evidenz-Waage** – ein Gewicht pro Signal – und zeigt **Prozente pro Zustand** (Daheim, Schläft, Weg). Die Waage kann Bifrost nur vorsichtiger machen. `tools/backtest.py` wendet den Rückblick auf eine Kopie deiner Datenbank an und zeigt, wie oft Bifrost „leer“ sagte, obwohl jemand drinnen war.

**Personen gibt es nur in Bifrost** – Benutzer in Home Assistant braucht es nicht. Im Tab Personen stehen nur Namen, die Art (Haushalt oder regelmässiger Besuch) und „darf allein daheim sein“. Alles Technische ordnest du im **Setup** direkt bei der Entität zu: Handys, Tracker und Kalender bekommen ein Dropdown „Gehört zu“ (Kalender auch „ganze Familie“); Entitäten der Kategorie **Zutritt** (Code, NFC, Fingerabdruck, „letzter Benutzer“) und smarte Schlösser zeigen die gemeldeten Benutzer, die du einer Person zuordnest, als Familien-Code markierst oder ignorierst – nicht zugeordnetes Aufschliessen zählt trotzdem als „jemand mit Berechtigung“. Bluetooth-Schlüssel (IRK) von iPhones gehören in Home Assistant (**Private BLE Device**); Bifrost liest die Tracker – siehe die Bluetooth-Hilfe im Setup. Aus den zugeordneten Quellen leitet Bifrost ab, wie **sichtbar** eine Person ist (gut / mittel / unsichtbar, anhand des HA-Standards `source_type`). Kinder ohne Handy gehören dazu: Sie gelten als daheim, bis Fakten dagegen sprechen, und Eintritte, die Bifrost nicht erklären kann, zählen als „Unbekannte – mindestens N“.

**Fragen statt raten.** Wenn Bifrost unsicher ist, fragt es – höchstens 3 Fragen und 5 Vorschläge am Tag, Sicherheit zuerst. Du antwortest *Ja / Nein / Vielleicht / Weiss nicht* und kannst den Grund benennen („Ratten“, „Putzfrau“). Antworten werden zu bekannten Ausnahmen; „Weiss nicht“ wird später nochmals gefragt.

**Wer hat geschaltet?** Bifrost liest bei jeder Änderung den Home-Assistant-Context. Ein Licht, das eine Automation geschaltet hat – oder eine gelernte Zeitschaltung, z. B. in Loxone – ist keine Person. Feuchte-Sprünge, steigendes CO₂ und Strom-Spitzen zählen ebenfalls als Ereignisse.

**Sprache.** Deutsch oder Englisch, einstellbar im Setup. Beim ersten Start übernimmt Bifrost die Sprache von Home Assistant.

**Bilanz.** Bifrost führt Buch: falsches „leer“, erkannte leere Zeit, Verdachte und Fehlalarme. Die Option `alarm_signal` wirkt erst, wenn die Freigabe grün ist (30 Tage Schattenmodus, 20 erkannte Abfahrten, 0 falsches „leer“, Datengesundheit ≥ 90 %, mindestens eine Person im Haushalt).

Neue Entitäten: `binary_sensor.bifrost_suspicious_entry`, `binary_sensor.bifrost_empty_confirmed` (nur mit `alarm_signal`), `sensor.bifrost_open_questions`, `sensor.bifrost_unknown_people`, `sensor.bifrost_person_<id>`.

### Tabs
| Tab | Was du siehst |
|---|---|
| **Status** | Aktuelles Ergebnis mit Prozent für Daheim, Schläft und Weg, Gründe, „Stimmt nicht“, Checkliste „Darf das Haus leer sein?“, Personen, verdächtiger Eintritt, Gästemodus, letzte 24 Stunden |
| **Personen** | Namen, Art, „darf allein daheim sein“ und wie sichtbar jede Person durch ihre Quellen ist; Unbekannte im Haus |
| **Haus** | Räume pro Stockwerk auf einem Raster über deinem eigenen Grundriss, eingefärbt nach dem, was passiert, Personen in ihrem Raum; Live-Signale, letzter Weg, Lücken. *Technisch* zeigt zusätzlich Entitäts-IDs, Herkunft, gelernte Verbindungen und Eingänge |
| **Mustererkennung** | Lernfortschritt; Bausteine · Personen · Abläufe als Ketten mit Linien (ODER / UND / Begleiter, Unter-Muster klappen auf, Einfach / Technisch); Muster als Entität einschalten; Detektoren (Grundlinie pro Signal, Wege zwischen Bereichen); Kalenderwörter |
| **Vorfälle** | Was nicht passte, gebündelt zu Ketten (Annäherung → Zugang → drinnen → Identität) mit Score; Fragen und Vorschläge – Ja / Nein / Vielleicht / Weiss nicht |
| **Bilanz** | Kennzahlen, Rückblick, „Stimmen die Prozente?“ und die Freigabe für das Alarm-Signal |
| **Setup** | Sprache, „Was Bifrost bei dir sieht“, Wert pro Signal (wertvoll / bringt nichts / träge) mit Filtern, Anleitung, Optimierungen, Bluetooth-Hilfe, Filter, Scanner und Konfigurator für alle Entitäten inkl. „Gehört zu“ und gemeldeter Benutzer |

### Installation
1. In Home Assistant **Einstellungen → Apps → App Store → ⋮ → Repositories** öffnen.
2. `https://github.com/magi1982/bifrost` hinzufügen.
3. **Bifrost** installieren, starten und über die Seitenleiste öffnen.
4. Im Tab **Setup** die Vorschläge prüfen, freigeben oder korrigieren. Fertig.

### Optionen
| Option | Standard | Beschreibung |
|---|---|---|
| `update_interval` | 30 s | Wie oft Bifrost neu bewertet |
| `phone_away_minutes` | 10 | So lange müssen alle Handys weg sein, bevor „Away“ gilt |
| `no_motion_minutes` | 15 | So lange ohne Aktivität, bevor „Away“ gilt |
| `shadow_mode` | an | Nur beobachten – nie etwas auslösen |
| `publish_entities` | an | Die `bifrost_*`-Entitäten anlegen |
| `use_learning` | an | Lernen, wie zuverlässig jeder Sensor ist, und Sensoren ignorieren, die auslösen, wenn niemand da ist |
| `learn_calendars` | an | Lernen, welche Kalendereinträge bedeuten, dass niemand da ist (nur Stichwörter, Titel werden nie gespeichert) |
| `event_stream` | an | Live auf Sensoränderungen hören (genaue Zeit und Reihenfolge) |
| `suspicious_entry_level` | 2 | 0 = aus, 1 = in der App melden, 2 = zusätzlich `binary_sensor.bifrost_suspicious_entry` einschalten |
| `person_entities` | an | Ein `sensor.bifrost_person_<id>` pro Person |
| `alarm_signal` | aus | `binary_sensor.bifrost_empty_confirmed` erlauben, sobald die Bilanz grün ist. Schaltet nie unscharf. |
| `log_level` | info | Detailgrad der Protokolle |

### Datenschutz & Sicherheit
Alles bleibt zu Hause. Keine Cloud, keine Telemetrie, keine Fremdbibliotheken. Die Oberfläche ist nur über Home Assistant erreichbar (Ingress), und die App läuft mit eigenem AppArmor-Profil (Sicherheitsbewertung 8 von 8). Bifrost schaltet eine Alarmanlage **nie** unscharf. Details in [SECURITY.md](SECURITY.md).

### Ausblick
Backtests und Freigabe auf echten Daten, dann das Signal an die Alarmanlage (1.0). Loxone-Anbindung (nur lesen) für Alarmzustand und NFC-Benutzer. Siehe [NEXT.md](NEXT.md).

---
MIT License
