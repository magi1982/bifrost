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
| `log_level` | info | Logging detail |

### Privacy & security
Everything stays in your home. No cloud, no telemetry, no dependencies outside the Python standard library. The UI is only reachable through Home Assistant. See [SECURITY.md](SECURITY.md).

### Roadmap
Learning from history, multi-step patterns, calendar learning, BLE room location, UniFi and Loxone connectors, house map. See [NEXT.md](NEXT.md).

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
| `log_level` | info | Detailgrad der Protokolle |

### Datenschutz & Sicherheit
Alles bleibt zu Hause. Keine Cloud, keine Telemetrie, keine Fremdbibliotheken. Die Oberfläche ist nur über Home Assistant erreichbar. Bifrost schaltet eine Alarmanlage **nie** unscharf. Details in [SECURITY.md](SECURITY.md).

### Ausblick
Lernen aus der Historie, mehrstufige Muster, Kalender-Lernen, BLE-Raumortung, UniFi- und Loxone-Anbindung, Hausplan. Siehe [NEXT.md](NEXT.md).

---
MIT License
