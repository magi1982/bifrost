# NEXT – roadmap & ideas

Ideas collected first, built only after approval.

## v0.2 – Learn
- Store state changes of all used signals locally; per-signal trust (Beta-Bayes): how often did a signal agree with the confirmed result?
- Dashboard tab: charts of confidence and states over days, "is learning helping?" curve.
- Timeline tab: what happened today, grouped by category.
- Own entities: `sensor.bifrost_expected_return`, `binary_sensor.bifrost_anomaly`, `switch.bifrost_guest_mode`, `switch.bifrost_auto_arm`.

## v0.3 – Patterns
- Sequential pattern mining (3–5+ steps, e.g. *calendar entry "office" → phone leaves → front door → no motion*), shown as processes with times between steps.
- Suggest patterns with ≥5 observations and ≥85 % accuracy; enable/disable per pattern; weekly drift check.
- Calendar learning: which calendar entries mean "away"; titles are never stored, only learned keywords per calendar.

## v0.4 – Location
- BLE scanners (e.g. Shelly) and iBeacon/IRK trackers; room fingerprints; setup assistant for BLE and IRK.
- Zigbee link quality as an extra room hint.
- House map: upload a floor plan (stored locally only), place rooms and sensors, live view.

## v0.5 – Connectors (optional, read-only)
- UniFi: client presence, VLAN/guest counts, DPI at category level (streaming, gaming).
- Loxone: person vs. automation for lights/blinds, presence blocks, alarm state, NFC access events.

## v1.0 – Act
- Release gate: 30 days shadow mode, ≥20 departures, 0 wrong "empty" decisions, data health ≥90 %.
- Only then: signal "house empty confirmed" to the alarm system. The alarm system arms itself. **Never disarm automatically.**
