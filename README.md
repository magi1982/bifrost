# Bifrost

**Local, explainable presence detection for Home Assistant.**
*Is anybody home?* Bifrost combines all the signals your home already has – phones, motion, doors, windows, modes, media, calendars – into one clear answer with a confidence and the reasons behind it.

> ⚠️ **Experimental (v0.5).** Bifrost runs in *shadow mode*: it observes, learns and explains. The only signal it can ever give your alarm is “house empty confirmed” – and only after you switch it on and the balance has been green for 30 days. Bifrost never disarms anything.

[🇬🇧 English](#english) · [🇩🇪 Deutsch](#deutsch)

---

## English

### What Bifrost does
1. **Scans** your Home Assistant: every entity, device and area – including disabled and unavailable ones.
2. **Sorts** every entity into one of 12 categories (Motion, Doors & windows, Manual use, Personal devices, Network, Media, Climate, Energy, Vehicles & robots, Modes, Calendar, Security) and gives it a role:

   | Role | Meaning |
   |---|---|
   | **Evidence** | Says something about presence (a phone at home, motion) |
   | **Trigger** | Starts a new check (front door opened) |
   | **Context** | Changes how to read the rest (calendar, holiday mode) |
   | **Blocker** | Makes "empty" impossible (guest mode, sleep mode) |
   | **Noise** | Looks like a person but is not (robot vacuum, pets) |
   | **Truth** | Confirms the result afterwards (alarm armed) |

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

**People live only in Bifrost** – no Home Assistant users are needed. The People tab holds only names, the kind (household or regular visitor) and “may be home alone”. Everything technical is assigned in **Setup**, right at the entity: phones, trackers and calendars get a “Belongs to” dropdown (calendars can belong to the whole household); entities with the role **Identity** (keypad, NFC, fingerprint, “last user”) and smart locks list the users they reported, which you assign to a person, mark as household code or ignore – unassigned unlocks still count as “someone authorised”. iPhone Bluetooth keys (IRK) have their own card in Setup. Children without phones are welcome: Bifrost then counts entries it cannot explain as “unknown – at least N”.

**Questions instead of guessing.** When Bifrost is unsure it asks – at most 3 questions and 5 suggestions a day, safety first. You answer *Yes / No / Maybe / Don't know* and can name the reason (“animals”, “cleaner”). Answers become known exceptions; “don't know” is asked again later.

**Who switched it?** Bifrost reads the Home Assistant context of every change. A light switched by an automation – or by a timer it learned, e.g. one in Loxone – is not a person. Humidity jumps, CO₂ rises and power spikes count as events too.

**Language.** German or English, set in Setup. On first start Bifrost uses the Home Assistant language.

**Balance.** Bifrost keeps score: wrong “empty”, detected empty time, suspicions and false alarms. The `alarm_signal` option only takes effect once the release gate is green (30 days in shadow mode, 20 detected departures, 0 wrong “empty”, data health ≥ 90 %).

New entities: `binary_sensor.bifrost_suspicious_entry`, `binary_sensor.bifrost_empty_confirmed` (only with `alarm_signal`), `sensor.bifrost_open_questions`, `sensor.bifrost_unknown_people`, `sensor.bifrost_person_<id>`.

### Tabs
| Tab | What you see |
|---|---|
| **Status** | Current result, confidence, reasons, “May the house be empty?” checklist, people, suspicious entry, learning progress, “That's wrong” correction, guest mode |
| **People** | Names, kind and “may be home alone”; overview of each person's sources; unknown people inside |
| **House** | Live: floors and areas from Home Assistant, what fires right now, the last path through the house, gaps. *Technical* adds entity ids, who switched it (hand / app / automation / timer), learned connections, entrances, exceptions, floor plan |
| **Pattern recognition** | Blocks · People · Routines with search and filters; open any pattern, expand its sub-patterns |
| **Deviations** | Things that did not fit (open / explained) |
| **Questions** | Questions and suggestions – Yes / No / Maybe / Don't know |
| **Calendars** | What Bifrost learned from your calendars (words, never full titles) |
| **Timeline** | Every change of a used signal and every decision of the last 24 hours |
| **Dashboard** | The last 14 days, average confidence, "Is learning helping?", sensor trust |
| **Balance** | Key figures and the release gate for the alarm signal |
| **Setup** | Language, guide “Which role for what?”, optimisations, Bluetooth keys, scanner and configurator for all entities incl. “Belongs to” and reported users |

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
Everything stays in your home. No cloud, no telemetry, no dependencies outside the Python standard library. The UI is only reachable through Home Assistant. See [SECURITY.md](SECURITY.md).

### Roadmap
BLE room location with ESP32 scanners, Loxone read-only connector for alarm and NFC. See [NEXT.md](NEXT.md).

---

## Deutsch

### Was Bifrost macht
1. **Scannt** dein Home Assistant: alle Entitäten, Geräte und Bereiche – auch deaktivierte und nicht verfügbare.
2. **Sortiert** jede Entität in eine von 12 Kategorien (Bewegung, Türen & Fenster, Manuelle Bedienung, Persönliche Geräte, Netzwerk, Medien, Klima, Energie, Fahrzeuge & Roboter, Modi, Kalender, Sicherheit) und gibt ihr eine Rolle:

   | Rolle | Bedeutung |
   |---|---|
   | **Evidence** (Hinweis) | Sagt etwas über Anwesenheit (Handy zu Hause, Bewegung) |
   | **Trigger** (Auslöser) | Startet eine neue Prüfung (Haustür geöffnet) |
   | **Context** (Kontext) | Verändert die Deutung (Kalender, Ferienmodus) |
   | **Blocker** | Macht „leer“ unmöglich (Gästemodus, Schlafmodus) |
   | **Noise** (Störquelle) | Sieht aus wie ein Mensch, ist aber keiner (Saugroboter, Haustiere) |
   | **Truth** (Bestätigung) | Bestätigt das Ergebnis im Nachhinein (Alarm scharf) |

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

**Personen gibt es nur in Bifrost** – Benutzer in Home Assistant braucht es nicht. Im Tab Personen stehen nur Namen, die Art (Haushalt oder regelmässiger Besuch) und „darf allein daheim sein“. Alles Technische ordnest du im **Setup** direkt bei der Entität zu: Handys, Tracker und Kalender bekommen ein Dropdown „Gehört zu“ (Kalender auch „ganze Familie“); Entitäten mit der Rolle **Wer (Identität)** (Code, NFC, Fingerabdruck, „letzter Benutzer“) und smarte Schlösser zeigen die gemeldeten Benutzer, die du einer Person zuordnest, als Familien-Code markierst oder ignorierst – nicht zugeordnetes Aufschliessen zählt trotzdem als „jemand mit Berechtigung“. Bluetooth-Schlüssel (IRK) von iPhones haben eine eigene Karte im Setup. Kinder ohne Handy gehören dazu: Bifrost zählt Eintritte, die es nicht erklären kann, als „Unbekannte – mindestens N“.

**Fragen statt raten.** Wenn Bifrost unsicher ist, fragt es – höchstens 3 Fragen und 5 Vorschläge am Tag, Sicherheit zuerst. Du antwortest *Ja / Nein / Vielleicht / Weiss nicht* und kannst den Grund benennen („Ratten“, „Putzfrau“). Antworten werden zu bekannten Ausnahmen; „Weiss nicht“ wird später nochmals gefragt.

**Wer hat geschaltet?** Bifrost liest bei jeder Änderung den Home-Assistant-Context. Ein Licht, das eine Automation geschaltet hat – oder eine gelernte Zeitschaltung, z. B. in Loxone – ist keine Person. Feuchte-Sprünge, steigendes CO₂ und Strom-Spitzen zählen ebenfalls als Ereignisse.

**Sprache.** Deutsch oder Englisch, einstellbar im Setup. Beim ersten Start übernimmt Bifrost die Sprache von Home Assistant.

**Bilanz.** Bifrost führt Buch: falsches „leer“, erkannte leere Zeit, Verdachte und Fehlalarme. Die Option `alarm_signal` wirkt erst, wenn die Freigabe grün ist (30 Tage Schattenmodus, 20 erkannte Abfahrten, 0 falsches „leer“, Datengesundheit ≥ 90 %).

Neue Entitäten: `binary_sensor.bifrost_suspicious_entry`, `binary_sensor.bifrost_empty_confirmed` (nur mit `alarm_signal`), `sensor.bifrost_open_questions`, `sensor.bifrost_unknown_people`, `sensor.bifrost_person_<id>`.

### Tabs
| Tab | Was du siehst |
|---|---|
| **Status** | Aktuelles Ergebnis, Sicherheit, Gründe, Checkliste „Darf das Haus leer sein?“, Personen, verdächtiger Eintritt, Lernfortschritt, „Stimmt nicht“-Korrektur, Gästemodus |
| **Personen** | Namen, Art und „darf allein daheim sein“; Übersicht der Quellen pro Person; Unbekannte im Haus |
| **Haus** | Live: Stockwerke und Bereiche aus Home Assistant, was gerade auslöst, der letzte Weg durchs Haus, Lücken. *Technisch* zeigt zusätzlich Entity-IDs, wer geschaltet hat (von Hand / App / Automation / Zeitplan), gelernte Verbindungen, Eingänge, Ausnahmen, Grundriss |
| **Mustererkennung** | Bausteine · Personen · Abläufe mit Suche und Filtern; jedes Muster öffnen, Unter-Muster auf- und zuklappen |
| **Abweichungen** | Was nicht gepasst hat (offen / erklärt) |
| **Fragen** | Fragen und Vorschläge – Ja / Nein / Vielleicht / Weiss nicht |
| **Kalender** | Was Bifrost aus deinen Kalendern gelernt hat (Wörter, nie ganze Titel) |
| **Verlauf** | Jede Änderung eines genutzten Signals und jede Entscheidung der letzten 24 Stunden |
| **Dashboard** | Die letzten 14 Tage, durchschnittliche Sicherheit, „Hilft das Lernen?“, Vertrauen pro Sensor |
| **Bilanz** | Kennzahlen und die Freigabe für das Alarm-Signal |
| **Setup** | Sprache, Anleitung „Welche Rolle wofür?“, Optimierungen, Bluetooth-Schlüssel, Scanner und Konfigurator für alle Entitäten inkl. „Gehört zu“ und gemeldeter Benutzer |

Neue Entitäten ab 0.2: `sensor.bifrost_expected_return` (übliche Rückkehrzeit an diesem Wochentag), `binary_sensor.bifrost_anomaly` (Aktivität, obwohl alle Handys weg sind), `binary_sensor.bifrost_guest_mode` und `sensor.bifrost_person_*` (zu Hause / weg pro Person).

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
Alles bleibt zu Hause. Keine Cloud, keine Telemetrie, keine Fremdbibliotheken. Die Oberfläche ist nur über Home Assistant erreichbar. Bifrost schaltet eine Alarmanlage **nie** unscharf. Details in [SECURITY.md](SECURITY.md).

### Ausblick
BLE-Raumortung mit ESP32-Scannern, Loxone-Anbindung (nur lesen) für Alarm und NFC. Siehe [NEXT.md](NEXT.md).

---
MIT License
