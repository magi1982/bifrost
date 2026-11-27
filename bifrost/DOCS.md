# Bifrost

Bifrost tells you whether anybody is home – with a confidence and the reasons. It learns your house by itself and never controls your alarm system.

[English](#english) · [Deutsch](#deutsch)

## English

### First steps
1. Start the app and open **Bifrost** in the sidebar. The language follows Home Assistant; change it in **Setup**.
2. **Setup** – Bifrost has already scanned your Home Assistant and switched on the signals it is sure about. Check the **Suggested** filter and correct wrong guesses (**Why?** shows the reasons).
3. **People** – add everybody who lives here, children without phones too. Pick their phones and calendars; optionally enter the NFC user of the keypad and the iPhone IRK (stored locally, never shown again). No Home Assistant users are needed.
4. Assign your sensors to **areas** (and areas to **floors**) in Home Assistant – the **House** tab is built from them.
5. Let Bifrost learn for a few days. It runs in **shadow mode** and does not trigger anything.

### Tabs
- **Status** – result, confidence, reasons, “May the house be empty?” checklist, people, suspicious entry, learning progress, “That's wrong” correction, guest mode.
- **People** – everybody in the household with their sources; unknown people inside.
- **House** – live: floors and areas from Home Assistant, what fires right now, the last path through the house, gaps (door without sensor, area without signal, signal without area). *Technical* adds entity ids, who switched it, learned connections, entrances, exceptions and the optional floor plan.
- **Pattern recognition** – Blocks · People · Routines, learned automatically. Open any pattern and expand its sub-patterns.
- **Deviations** – what did not fit (open / explained).
- **Questions** – when Bifrost is unsure it asks (max. 3 questions and 5 suggestions a day). Answer *Yes / No / Maybe / Don't know* and optionally name the reason.
- **Calendars** – words Bifrost learned from your calendars (never full titles).
- **Signals**, **Timeline**, **Dashboard**, **Balance**, **Setup**.

### Who switched it?
Bifrost reads the Home Assistant context of every change: by hand, via app or by an automation. A light switched by an automation – or by a timer Bifrost learned (same time on 5 of the last 14 days, e.g. a Loxone timer) – is not a person. Humidity jumps, CO₂ rises, power spikes and running water count as events.

### Safety
After an entry the house stays “not empty” for 15 minutes. “Empty” needs every person away, no unknown people inside, the last one out detected and healthy data. A door opened from outside while everybody is away or asleep, with no explanation, is a **suspicious entry** (option `suspicious_entry_level`). `binary_sensor.bifrost_empty_confirmed` only turns on with option `alarm_signal` **and** a green balance (30 days, ≥ 20 departures, 0 wrong “empty”, data health ≥ 90 %). Bifrost never disarms anything.

### Entities
`sensor.bifrost_home_status`, `binary_sensor.bifrost_house_empty`, `sensor.bifrost_confidence`, `sensor.bifrost_reason`, `sensor.bifrost_data_health`, `sensor.bifrost_expected_return`, `binary_sensor.bifrost_anomaly`, `binary_sensor.bifrost_guest_mode`, `binary_sensor.bifrost_suspicious_entry`, `binary_sensor.bifrost_empty_confirmed`, `sensor.bifrost_open_questions`, `sensor.bifrost_unknown_people`, `sensor.bifrost_person_<id>`.

Example automation (notification only):
```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.bifrost_suspicious_entry
    to: "on"
actions:
  - action: notify.notify
    data:
      message: "Bifrost: suspicious entry at {{ state_attr('binary_sensor.bifrost_suspicious_entry', 'door') }}"
```

### Tips
- Put motion sensors inside **and** outside next to every entrance – then Bifrost sees the direction.
- Give iPhones a **fixed Wi-Fi address** for your home network (Settings → Wi-Fi → (i) → Private Wi-Fi Address: Fixed).
- Mark robots, pets and outdoor sensors as **Noise** if they are not detected automatically.

### Note
Entities created by an app through the REST API disappear after a Home Assistant restart until Bifrost publishes them again (within one update interval).

## Deutsch

### Erste Schritte
1. App starten und **Bifrost** in der Seitenleiste öffnen. Die Sprache folgt Home Assistant; umstellen im **Setup**.
2. **Setup** – Bifrost hat dein Home Assistant schon gescannt und die sicheren Signale eingeschaltet. Filter **Vorgeschlagen** prüfen und falsche Vermutungen korrigieren (**Warum?** zeigt die Gründe).
3. **Personen** – alle anlegen, die hier wohnen, auch Kinder ohne Handy. Handys und Kalender wählen; optional NFC-Benutzer am Code Touch und iPhone-IRK eintragen (lokal gespeichert, nie wieder angezeigt). Benutzer in Home Assistant braucht es nicht.
4. Sensoren in Home Assistant **Bereichen** zuweisen (und Bereiche **Stockwerken**) – daraus entsteht der Tab **Haus**.
5. Bifrost ein paar Tage lernen lassen. Es läuft im **Schattenmodus** und löst nichts aus.

### Tabs
- **Status** – Ergebnis, Sicherheit, Gründe, Checkliste „Darf das Haus leer sein?“, Personen, verdächtiger Eintritt, Lernfortschritt, „Stimmt nicht“, Gästemodus.
- **Personen** – alle im Haushalt mit ihren Quellen; Unbekannte im Haus.
- **Haus** – live: Stockwerke und Bereiche aus Home Assistant, was gerade auslöst, der letzte Weg durchs Haus, Lücken. *Technisch* zeigt zusätzlich Entity-IDs, wer geschaltet hat, gelernte Verbindungen, Eingänge, Ausnahmen und den Grundriss.
- **Mustererkennung** – Bausteine · Personen · Abläufe, selbst gelernt. Jedes Muster öffnen, Unter-Muster auf- und zuklappen.
- **Abweichungen** – was nicht gepasst hat (offen / erklärt).
- **Fragen** – wenn Bifrost unsicher ist, fragt es (max. 3 Fragen und 5 Vorschläge pro Tag). Antworten mit *Ja / Nein / Vielleicht / Weiss nicht*, optional mit Grund.
- **Kalender** – Wörter, die Bifrost aus deinen Kalendern gelernt hat (nie ganze Titel).
- **Signale**, **Verlauf**, **Dashboard**, **Bilanz**, **Setup**.

### Wer hat geschaltet?
Bifrost liest bei jeder Änderung den Home-Assistant-Context: von Hand, per App oder durch eine Automation. Ein Licht, das eine Automation geschaltet hat – oder eine gelernte Zeitschaltung (gleiche Zeit an 5 der letzten 14 Tage, z. B. in Loxone) – ist keine Person. Feuchte-Sprünge, steigendes CO₂, Strom-Spitzen und laufendes Wasser zählen als Ereignisse.

### Sicherheit
Nach einem Eintritt bleibt das Haus 15 Minuten „nicht leer“. „Leer“ braucht alle Personen weg, keine Unbekannten im Haus, den erkannten letzten Rausgehenden und gesunde Daten. Wird eine Tür von aussen geöffnet, während alle weg sind oder schlafen, und nichts erklärt es, ist das ein **verdächtiger Eintritt** (Option `suspicious_entry_level`). `binary_sensor.bifrost_empty_confirmed` schaltet nur mit der Option `alarm_signal` **und** grüner Bilanz ein (30 Tage, ≥ 20 Abfahrten, 0 falsches „leer“, Datengesundheit ≥ 90 %). Bifrost schaltet nie etwas unscharf.

### Tipps
- Bei jedem Eingang einen Bewegungsmelder innen **und** aussen – dann sieht Bifrost die Richtung.
- iPhones im Heimnetz eine **feste WLAN-Adresse** geben (Einstellungen → WLAN → (i) → Private WLAN-Adresse: Fest).
- Roboter, Haustiere und Aussensensoren als **Störquelle** markieren, falls Bifrost sie nicht selbst erkennt.
