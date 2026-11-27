# Bifrost

Bifrost tells you whether anybody is home – with a confidence and the reasons. It learns your house by itself and never controls your alarm system.

[English](#english) · [Deutsch](#deutsch)

## English

### First steps
1. Start the app and open **Bifrost** in the sidebar. The language follows Home Assistant; change it in **Setup**.
2. **Setup** – Bifrost has already scanned your Home Assistant and switched on the signals it is sure about. Go through **Optimisations** (one suggestion per signal) and the **Suggested** filter; **Why?** shows the reasons, “Which category for what?” explains the categories. Filter by status, category, floor, area, integration or kind, or show only signals without area, without owner or with an optimisation – the filters are remembered.
3. **People** – add everybody who lives here by name, children without phones too. No Home Assistant users are needed.
4. **Setup** – assign phones and calendars with **Belongs to**; give keypad/NFC/“last user” entities the category **Access** and assign the users they report. The card **What Bifrost sees in your home** shows which kinds of signals were found and what they enable.
5. Assign your sensors to **areas** (and areas to **floors**) in Home Assistant – the **House** tab is built from them.
6. Let Bifrost learn for a few days. It runs in **shadow mode** and does not trigger anything.

### Tabs
- **Status** – the result with a percentage for Home, Asleep and Away (and how Bifrost calculated it), reasons, “Is Bifrost wrong?” right under the result, “May the house be empty?” checklist, people, suspicious entry, guest mode.
- **People** – everybody in the household with their sources and how visible they are; unknown people inside.
- **House** – the house map in three tabs, all floors at once: **Live** shows who is where (family as a phone with the name) and which rooms are active; **Configuration** shows gateways, sensors, Bluetooth devices, doors and windows – **Edit map** per floor: draw rooms (several rectangles join into one room), *Outside area* (terrace, pool, path to the entrance – never counts as inside), *Hull* (the outline of the house, e.g. with an attached garage), stairs, doors, windows, *Place device* for gateways and sensors, *Floor plan* to layer up to four pictures (move, size, rotation, opacity); **Signal** shows in colour how well Bifrost can locate, on a grey map. Below: **What is happening** – the last hour as a lane per area – then live signals, the last path, gaps.
- **Patterns** – learning progress, then Blocks · People · Routines. Open a pattern: a chain with lines, OR / AND groups, companions and sub-patterns that open inline; *Simple* or *Technical*. Switch **As an entity in Home Assistant** on to use it in your own automations. Detectors (baseline, paths) and calendar words at the end.
- **Incidents** – what did not fit, bundled into a chain approach → access → inside → identity with a score. Questions and suggestions are answered here (*Yes / No / Maybe / Don't know*, optionally with a name).
- **Balance** – key figures, hindsight, calibration and the release gate. **Setup** – language, what Bifrost sees in your home, guide, optimisations, Bluetooth help, filters and all entities; **Data** at an entity shows its state, attributes and 24 h history from Home Assistant.

### Access system (optional)
Keypad, NFC, fingerprint or smart lock: give the entity that reports who unlocked the category **Access** in Setup (smart locks are read automatically). The reported users appear right under the entity; assign each to a person, mark it as **household code**, ignore it – or leave it unassigned (still counts as “someone authorised”). “Denied” never explains an entry.

### Bluetooth with Shelly (optional)
Shellys with Bluetooth hear phones, but they do not create entities for them – in Home Assistant they are **Bluetooth proxies**. Home Assistant turns what they hear into entities, and Bifrost reads those:
1. In the Shelly integration switch on the **Bluetooth scanner** of each Shelly (passive is enough) and assign every Shelly to an **area**.
2. **iPhone:** add the Home Assistant integration **Private BLE Device** and enter the iPhone's IRK (Identity Resolving Key). It creates a tracker with `source_type: bluetooth_le`. The key stays in Home Assistant – Bifrost no longer stores keys.
3. **Room per person (optional):** the add-on integration **Bermuda** (HACS) reports the nearest area of each device. Bifrost uses it as a room source.
4. **Tags and Android:** the integration **iBeacon Tracker**; Android phones can send as a beacon via the Companion app.
5. In **Setup** assign the new tracker (or Bermuda's area sensor) to the person with **Belongs to**.

How to get an iPhone's IRK: on a Mac paired with the iPhone, search *Keychain Access* for “Bluetooth” and copy the *Remote IRK*; alternatively an ESP32 with ESPresense has an enrolment mode.

### Visibility per person
Bifrost works out by itself how well it can see each person, from the sources assigned in Setup – using the Home Assistant standard `source_type` of a tracker, not the integration's name:
- **Well visible** – a GPS phone, Bluetooth with a room, or a code/NFC user.
- **Partly visible** – only Wi-Fi (`router`) or Bluetooth without a room: “away” counts only after a longer time.
- **Invisible** – no own source (e.g. a child without a phone): counts as home until facts say otherwise. Without people in the household the alarm signal stays blocked.

### New sensors and notifications
New entities are highlighted as **New** in Setup and announced on Status, so none is overlooked. In the Setup card **Notifications** pick your phone (a notify service of the Home Assistant app) – Bifrost then sends a message once for every batch of new sensors. Entities disabled in Home Assistant are hidden; the filter *Disabled in HA* shows them.

Energy, water and air values (power, CO₂, humidity) never count as somebody being there – only their jumps (shower, cooking) help patterns.

### Signal value
Bifrost judges every used signal by itself: **Valuable**, **Helps a little**, **Brings nothing**, **Slow** (stays on for long – typically a summary zone from another system) or **Still learning**. The verdict and its reason stand at the entity in Setup; the filters *Brings nothing* and *Slow* show them all. Bifrost only suggests switching such a signal off – you decide. In the House tab they are archived; **Show archived** brings them back.

### Who switched it?
Bifrost reads the Home Assistant context of every change: by hand, via app or by an automation. A light switched by an automation – or by a timer Bifrost learned (same time on 5 of the last 14 days, e.g. a Loxone timer) – is not a person. Humidity jumps, CO₂ rises, power spikes and running water count as events.

### Safety
After an entry the house stays “not empty” for 15 minutes. “Empty” needs every person away, no unknown people inside, the last one out detected (confirmed from outside or by a phone leaving – quiet alone is no proof), healthy data and Bifrost running for at least 10 minutes. If the safety check itself fails, Bifrost never says “empty”. A door opened from outside while everybody is away or asleep, with no explanation, is a **suspicious entry** (option `suspicious_entry_level`). `binary_sensor.bifrost_empty_confirmed` only turns on with option `alarm_signal` **and** a green balance (30 days, ≥ 20 departures, 0 wrong “empty”, data health ≥ 90 %). Bifrost never disarms anything.

### Learning from hindsight
Bifrost learns only from what is certain afterwards – never from its own live decision: quiet between a confirmed exit and an entry was *certainly empty*; activity inside, or quiet after which activity resumes without anybody coming in (e.g. a child upstairs), was *certainly home*. From this it learns one weight per signal (the **evidence scale**) and shows on **Status** a percentage for Home, Asleep and Away. **Balance** shows the hindsight summary and whether the percentages were right. To test on your own data, copy the database from `/data` and run `python3 tools/backtest.py bifrost.db` – everything stays on your machine.

### Entities
`sensor.bifrost_p_home`, `sensor.bifrost_p_asleep`, `sensor.bifrost_p_away`, `binary_sensor.bifrost_<slug>` (patterns you switched on), `sensor.bifrost_home_status`, `binary_sensor.bifrost_house_empty`, `sensor.bifrost_confidence`, `sensor.bifrost_reason`, `sensor.bifrost_data_health`, `sensor.bifrost_expected_return`, `binary_sensor.bifrost_anomaly`, `binary_sensor.bifrost_guest_mode`, `binary_sensor.bifrost_suspicious_entry`, `binary_sensor.bifrost_empty_confirmed`, `sensor.bifrost_open_questions`, `sensor.bifrost_unknown_people`, `sensor.bifrost_person_<id>`.

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
- Switch robots, pets and outdoor sensors off in Setup if they are not detected automatically.

### Note
Entities created by an app through the REST API disappear after a Home Assistant restart until Bifrost publishes them again (within one update interval).

### Entities via MQTT (0.12)
With the **Mosquitto broker** installed, Bifrost publishes its entities via MQTT Discovery under the device **Bifrost** (nothing to configure). Without a broker it falls back to `/api/states`.
- `binary_sensor.bifrost_empty_confirmed` is never left on by accident: it is written *off* on start, stop and errors; on a crash every Bifrost entity becomes *unavailable*. For an alarm system: arm only while it is **on** (unavailable counts as not empty). In the fallback mode also check the attribute `valid_until`.
- **After the update to 0.12 – check in HA:** Settings → Devices → *Bifrost* shows all entities; old Bifrost states are removed automatically, leftovers are listed in Setup → *Bifrost entities* with a remove button; dashboards that used old entities may need the entity picked again.

## Deutsch

### Erste Schritte
1. App starten und **Bifrost** in der Seitenleiste öffnen. Die Sprache folgt Home Assistant; umstellen im **Setup**.
2. **Setup** – Bifrost hat dein Home Assistant schon gescannt und die sicheren Signale eingeschaltet. **Optimierungen** durchgehen (ein Vorschlag pro Signal) und den Filter **Vorgeschlagen** prüfen; **Warum?** zeigt die Gründe, „Welche Kategorie wofür?“ erklärt die Kategorien. Filtern nach Status, Kategorie, Stockwerk, Bereich, Integration oder Art, oder nur Signale ohne Bereich, ohne Besitzer oder mit Optimierung zeigen – die Filter werden gemerkt.
3. **Personen** – alle, die hier wohnen, mit Namen anlegen, auch Kinder ohne Handy. Benutzer in Home Assistant braucht es nicht.
4. **Setup** – Handys und Kalender mit **Gehört zu** zuordnen; Code-/NFC-/„letzter Benutzer“-Entitäten die Kategorie **Zutritt** geben und die gemeldeten Benutzer zuordnen. Die Karte **Was Bifrost bei dir sieht** zeigt, welche Arten von Signalen gefunden wurden und was damit möglich wird.
5. Sensoren in Home Assistant **Bereichen** zuweisen (und Bereiche **Stockwerken**) – daraus entsteht der Tab **Haus**.
6. Bifrost ein paar Tage lernen lassen. Es läuft im **Schattenmodus** und löst nichts aus.

### Tabs
- **Status** – das Ergebnis mit Prozent für Daheim, Schläft und Weg (und wie Bifrost gerechnet hat), Gründe, „Liegt Bifrost falsch?“ direkt darunter, Checkliste „Darf das Haus leer sein?“, Personen, verdächtiger Eintritt, Gästemodus.
- **Personen** – alle im Haushalt mit ihren Quellen und wie sichtbar sie sind; Unbekannte im Haus.
- **Haus** – die Hauskarte in drei Reitern, alle Stockwerke zugleich: **Live** zeigt, wer wo ist (Familie als Handy mit Namen) und welche Räume aktiv sind; **Konfiguration** zeigt Gateways, Melder, Bluetooth-Geräte, Türen und Fenster – **Karte bearbeiten** pro Stockwerk: Räume zeichnen (mehrere Rechtecke werden ein Raum), *Aussenbereich* (Terrasse, Pool, Weg zum Eingang – zählt nie als innen), *Hülle* (Umriss des Hauses, z. B. mit angebauter Garage), Treppe, Türen, Fenster, *Gerät setzen* für Gateways und Melder, *Grundriss* um bis zu vier Bilder übereinanderzulegen (verschieben, Grösse, Drehung, Deckkraft); **Signal** zeigt farbig auf grauer Karte, wie gut Bifrost orten kann. Darunter: **Was gerade passiert** – die letzte Stunde als Spur pro Bereich – dann Live-Signale, letzter Weg, Lücken.
- **Mustererkennung** – Lernfortschritt, dann Bausteine · Personen · Abläufe. Ein Muster öffnen: eine Kette mit Linien, ODER-/UND-Gruppen, Begleitern und Unter-Mustern, die direkt aufklappen; *Einfach* oder *Technisch*. **Als Entität in Home Assistant** einschalten, um es in eigenen Automationen zu nutzen. Am Ende Detektoren (Grundlinie, Wege) und Kalenderwörter.
- **Vorfälle** – was nicht passte, gebündelt zu einer Kette Annäherung → Zugang → drinnen → Identität mit Score. Fragen und Vorschläge beantwortest du hier (*Ja / Nein / Vielleicht / Weiss nicht*, optional mit Namen).
- **Bilanz** – Kennzahlen, Rückblick, Kalibrierung und die Freigabe. **Setup** – Sprache, was Bifrost bei dir sieht, Anleitung, Optimierungen, Bluetooth-Hilfe, Filter und alle Entitäten; **Daten** bei einer Entität zeigt Zustand, Attribute und den Verlauf der letzten 24 Stunden aus Home Assistant.

### Zugangssystem (optional)
Code-Tastatur, NFC, Fingerabdruck oder smartes Schloss: Gib der Entität, die meldet, wer aufgeschlossen hat, im Setup die Kategorie **Zutritt** (smarte Schlösser liest Bifrost automatisch). Die gemeldeten Benutzer erscheinen direkt darunter; ordne jeden einer Person zu, markiere ihn als **Familien-Code**, ignoriere ihn – oder lass ihn offen (zählt trotzdem als „jemand mit Berechtigung“). „Verweigert“ erklärt nie einen Eintritt.

### Bluetooth mit Shelly (optional)
Shellys mit Bluetooth hören Handys, legen dafür aber keine Entitäten an – in Home Assistant sind sie **Bluetooth-Proxys**. Home Assistant macht aus dem Gehörten Entitäten, und die liest Bifrost:
1. In der Shelly-Integration bei jedem Shelly den **Bluetooth-Scanner** einschalten (passiv reicht) und jeden Shelly einem **Bereich** zuordnen.
2. **iPhone:** in Home Assistant die Integration **Private BLE Device** hinzufügen und den IRK (Identity Resolving Key) des iPhones eintragen. Sie legt einen Tracker mit `source_type: bluetooth_le` an. Der Schlüssel bleibt in Home Assistant – Bifrost speichert keine Schlüssel mehr.
3. **Raum pro Person (optional):** die Zusatz-Integration **Bermuda** (HACS) meldet für jedes Gerät den nächsten Bereich. Bifrost nutzt das als Raum-Quelle.
4. **Tags und Android:** die Integration **iBeacon Tracker**; Android-Handys können über die Companion-App selbst als Beacon senden.
5. Im **Setup** den neuen Tracker (oder den Bereich-Sensor von Bermuda) mit **Gehört zu** der Person zuordnen.

So kommst du an den IRK eines iPhones: Auf einem Mac, der mit dem iPhone gekoppelt ist, in der *Schlüsselbundverwaltung* nach „Bluetooth“ suchen und den *Remote IRK* kopieren; alternativ hat ein ESP32 mit ESPresense einen Anlern-Modus.

### Sichtbarkeit pro Person
Bifrost leitet selbst ab, wie gut es eine Person sieht – aus den im Setup zugeordneten Quellen, anhand des Home-Assistant-Standards `source_type` eines Trackers, nicht am Namen der Integration:
- **Gut sichtbar** – Handy mit GPS, Bluetooth mit Raum oder ein Code-/NFC-Benutzer.
- **Mittel sichtbar** – nur WLAN (`router`) oder Bluetooth ohne Raum: „weg“ gilt erst nach längerer Zeit.
- **Unsichtbar** – keine eigene Quelle (z. B. ein Kind ohne Handy): gilt als daheim, bis Fakten dagegen sprechen. Ohne Personen im Haushalt bleibt das Alarm-Signal gesperrt.

### Neue Sensoren und Benachrichtigungen
Neue Entitäten sind im Setup als **Neu** markiert und werden im Status angezeigt – so übersiehst du keine. In der Setup-Karte **Benachrichtigungen** wählst du dein Handy (Benachrichtigungsdienst der Home-Assistant-App) – Bifrost schickt dann für neue Sensoren einmal eine Nachricht. In Home Assistant deaktivierte Entitäten sind ausgeblendet; der Filter *In HA deaktiviert* zeigt sie.

Energie-, Wasser- und Luftwerte (Strom, CO₂, Feuchte) zählen nie als „jemand ist da“ – nur ihre Sprünge (Dusche, Kochen) helfen den Mustern.

### Wert pro Signal
Bifrost bewertet jedes genutzte Signal selbst: **Wertvoll**, **Hilft wenig**, **Bringt nichts**, **Träge** (bleibt lange an – meist eine zusammengefasste Zone aus einem anderen System) oder **Lernt noch**. Urteil und Grund stehen im Setup bei der Entität; die Filter *Bringt nichts* und *Träge* zeigen alle. Bifrost schlägt das Ausschalten nur vor – du entscheidest. Im Haus-Tab sind sie archiviert; **Archivierte anzeigen** holt sie zurück.

### Wer hat geschaltet?
Bifrost liest bei jeder Änderung den Home-Assistant-Context: von Hand, per App oder durch eine Automation. Ein Licht, das eine Automation geschaltet hat – oder eine gelernte Zeitschaltung (gleiche Zeit an 5 der letzten 14 Tage, z. B. in Loxone) – ist keine Person. Feuchte-Sprünge, steigendes CO₂, Strom-Spitzen und laufendes Wasser zählen als Ereignisse.

### Sicherheit
Nach einem Eintritt bleibt das Haus 15 Minuten „nicht leer“. „Leer“ braucht alle Personen weg, keine Unbekannten im Haus, den erkannten letzten Rausgehenden (von aussen bestätigt oder durch ein Handy, das geht – Ruhe allein beweist nichts), gesunde Daten und dass Bifrost seit mindestens 10 Minuten läuft. Schlägt die Sicherheitsprüfung selbst fehl, sagt Bifrost nie „leer“. Wird eine Tür von aussen geöffnet, während alle weg sind oder schlafen, und nichts erklärt es, ist das ein **verdächtiger Eintritt** (Option `suspicious_entry_level`). `binary_sensor.bifrost_empty_confirmed` schaltet nur mit der Option `alarm_signal` **und** grüner Bilanz ein (30 Tage, ≥ 20 Abfahrten, 0 falsches „leer“, Datengesundheit ≥ 90 %). Bifrost schaltet nie etwas unscharf.

### Lernen aus dem Rückblick
Bifrost lernt nur aus dem, was im Nachhinein sicher ist – nie aus der eigenen Live-Entscheidung: Ruhe zwischen bestätigtem Austritt und Eintritt war *sicher leer*; Aktivität drinnen oder Ruhe, nach der es drinnen weitergeht, ohne dass jemand hereinkam (z. B. ein Kind oben), war *sicher daheim*. Daraus lernt es ein Gewicht pro Signal (die **Evidenz-Waage**) und zeigt im **Status** Prozente für Daheim, Schläft und Weg (`sensor.bifrost_p_home`, `sensor.bifrost_p_asleep`, `sensor.bifrost_p_away`). Die **Bilanz** zeigt den Rückblick und ob die Prozente gestimmt haben. Zum Testen mit eigenen Daten die Datenbank aus `/data` kopieren und `python3 tools/backtest.py bifrost.db` ausführen – alles bleibt auf deinem Rechner.

### Tipps
- Bei jedem Eingang einen Bewegungsmelder innen **und** aussen – dann sieht Bifrost die Richtung.
- iPhones im Heimnetz eine **feste WLAN-Adresse** geben (Einstellungen → WLAN → (i) → Private WLAN-Adresse: Fest).
- Roboter, Haustiere und Aussensensoren im Setup ausschalten, falls Bifrost sie nicht selbst erkennt.

### Entitäten über MQTT (0.12)
Mit dem **Mosquitto broker** veröffentlicht Bifrost seine Entitäten über MQTT Discovery unter dem Gerät **Bifrost** (nichts einzustellen). Ohne Broker schreibt es wie bisher über `/api/states`.
- `binary_sensor.bifrost_empty_confirmed` bleibt nie versehentlich an: beim Start, Stopp und bei Fehlern wird es *aus* geschrieben; bei einem Absturz werden alle Bifrost-Entitäten *nicht verfügbar*. Für eine Alarmanlage: nur scharf schalten, solange es **an** ist (nicht verfügbar zählt als nicht leer). Im Rückfall-Modus zusätzlich das Attribut `valid_until` prüfen.
- **Nach dem Update auf 0.12 – in HA prüfen:** Einstellungen → Geräte → *Bifrost* zeigt alle Entitäten; alte Bifrost-Zustände entfernt Bifrost selbst, Reste stehen im Setup unter *Bifrost-Entitäten* mit „Entfernen“; Dashboards mit alten Entitäten brauchen evtl. eine neue Auswahl.
