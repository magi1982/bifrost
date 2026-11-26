# Bifrost

Bifrost tells you whether anybody is home – with a confidence and the reasons.

## First steps
1. Start the app and open **Bifrost** in the sidebar.
2. Open **Setup**. Bifrost has already scanned your Home Assistant and switched on the signals it is sure about (for example phones, motion sensors, door and window contacts, guest and sleep modes).
3. Check the **Suggested** filter. Switch on what fits, or pick a better category and role. Press **Why?** to see the reasons for every guess.
4. Watch the **Status** tab for a few days. Bifrost runs in **shadow mode** and does not trigger anything.

## Tabs
- **Status** – the current result, confidence, reasons and the last 24 hours.
- **Signals** – which signals are used, grouped by category.
- **Timeline** – every change of a used signal and every Bifrost decision of the last 24 hours.
- **Dashboard** – the last 14 days, average confidence, "Is learning helping?" and how much Bifrost trusts each sensor.
- **Signals** – which signals are used, grouped by category. "Use all suggestions" switches on every suggestion of a category.
- **Setup** – scanner and sensor configurator for all entities, with filters by area and integration.

## Patterns
Bifrost looks at the hour before every departure, arrival and bedtime. Steps that keep happening in the same order become a suggested pattern (5+ times, at least 85 % accurate). Switch a pattern on to get `binary_sensor.bifrost_pattern_<id>`. Bifrost checks every 6 hours whether the pattern still holds; if not, it is marked "Changed". Patterns only add reasons – they never change the decision on their own.

## Calendars
Switch on the calendars you want Bifrost to use (Setup, category "Time & calendar"). Bifrost compares their entries of the last 6 weeks with its decisions and learns keywords that mean "away", for example "office". Full titles are never stored. Switch this off with the option `learn_calendars`.

## Guest mode
Switch it on in the Status tab when you have guests. Bifrost then never says the house is empty.

## Learning
When a decision stays the same for 30 minutes with at least 85 % confidence, Bifrost checks every used signal against it. A motion sensor that fires while the house is confirmed empty (a pet, a robot) loses trust. After 5 observations below 30 % trust it no longer counts as activity. Switch this off with the option `use_learning`.

## Entities
`sensor.bifrost_home_status`, `binary_sensor.bifrost_house_empty`, `sensor.bifrost_confidence`, `sensor.bifrost_reason`, `sensor.bifrost_data_health`, `sensor.bifrost_expected_return`, `binary_sensor.bifrost_anomaly`, `binary_sensor.bifrost_guest_mode`, `sensor.bifrost_person_*`.

Example automation (notification only):
```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.bifrost_house_empty
    to: "on"
    for: "00:05:00"
conditions:
  - condition: numeric_state
    entity_id: sensor.bifrost_confidence
    above: 90
actions:
  - action: notify.notify
    data:
      message: "Bifrost: the house looks empty ({{ states('sensor.bifrost_reason') }})"
```

## Tips for better results
- Create a **person** for everybody in your household and assign their phone.
- Give iPhones a **fixed Wi-Fi address** for your home network (Settings → Wi-Fi → (i) → Private Wi-Fi Address: Fixed) so the router always recognises them.
- Mark robots, pets and outdoor sensors as **Noise** if they are not detected automatically.

## Note
Entities created by an app through the REST API disappear after a Home Assistant restart until Bifrost publishes them again (within one update interval).
