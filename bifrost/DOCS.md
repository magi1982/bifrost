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
- **Setup** – scanner and sensor configurator for all entities.

## Entities
`sensor.bifrost_home_status`, `binary_sensor.bifrost_house_empty`, `sensor.bifrost_confidence`, `sensor.bifrost_reason`, `sensor.bifrost_data_health`.

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
