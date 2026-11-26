# Bifrost

**Local, explainable presence detection for Home Assistant.**
*Is anybody home?* Bifrost combines all the signals your home already has – phones, motion, doors, windows, modes, media, calendars – into one clear answer with a confidence and the reasons behind it.

> ⚠️ **Experimental (v0.1).** Bifrost runs in *shadow mode*: it observes and explains, it never triggers anything.

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

### Tabs
| Tab | What you see |
|---|---|
| **Status** | Current result, confidence, reasons, last 24 hours, guest mode |
| **Timeline** | Every change of a used signal and every decision of the last 24 hours |
| **Dashboard** | The last 14 days, average confidence, "Is learning helping?", sensor trust |
| **Patterns** | Recurring step-by-step processes before leaving, coming home or going to sleep – switch each on or off |
| **Calendars** | What Bifrost learned from your calendars (keywords that mean away) |
| **Signals** | Used signals by category, "Use all suggestions" |
| **Setup** | Scanner and sensor configurator for all entities, filters by area and integration |

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
| `log_level` | info | Logging detail |

### Privacy & security
Everything stays in your home. No cloud, no telemetry, no dependencies outside the Python standard library. The UI is only reachable through Home Assistant. See [SECURITY.md](SECURITY.md).

### Roadmap
BLE room location, UniFi and Loxone connectors, house map. See [NEXT.md](NEXT.md).

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

### Tabs
| Tab | Was du siehst |
|---|---|
| **Status** | Aktuelles Ergebnis, Sicherheit, Gründe, letzte 24 Stunden, Gästemodus |
| **Timeline** | Jede Änderung eines genutzten Signals und jede Entscheidung der letzten 24 Stunden |
| **Dashboard** | Die letzten 14 Tage, durchschnittliche Sicherheit, „Hilft das Lernen?“, Vertrauen pro Sensor |
| **Patterns** | Wiederkehrende Abläufe vor dem Weggehen, Heimkommen oder Schlafengehen – einzeln ein- und ausschaltbar |
| **Calendars** | Was Bifrost aus deinen Kalendern gelernt hat (Stichwörter, die „weg“ bedeuten) |
| **Signals** | Genutzte Signale nach Kategorie, „Alle Vorschläge übernehmen“ |
| **Setup** | Scanner und Sensor-Konfigurator für alle Entitäten, Filter nach Bereich und Integration |

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
| `log_level` | info | Detailgrad der Protokolle |

### Datenschutz & Sicherheit
Alles bleibt zu Hause. Keine Cloud, keine Telemetrie, keine Fremdbibliotheken. Die Oberfläche ist nur über Home Assistant erreichbar. Bifrost schaltet eine Alarmanlage **nie** unscharf. Details in [SECURITY.md](SECURITY.md).

### Ausblick
BLE-Raumortung, UniFi- und Loxone-Anbindung, Hausplan. Siehe [NEXT.md](NEXT.md).

---
MIT License
