"""Demo household: a fully wired BifrostService with 4 weeks of synthetic data (example names only).

Used by integration tests and by tools/demo_server.py for screenshots and GUI checks.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "bifrost" / "app"))

from sim import META, household  # noqa: E402

from bifrost_app.service import BifrostService  # noqa: E402
from bifrost_app.store import Store  # noqa: E402

PLATFORM = {"device_tracker.phone_a": "mobile_app", "device_tracker.phone_b": "unifi"}
FLOOR_OF = {
    "Outside": "outside",
    "Driveway": "outside",
    "Entrance": "ground",
    "Garage": "ground",
    "Hallway": "ground",
    "Cloakroom": "ground",
    "Living": "ground",
    "Kitchen": "ground",
    "Upstairs": "upper",
    "Bathroom": "upper",
    "Attic": "upper",
}
EXTRA = [
    ("light.kitchen", "Kitchen light", "off", {}),
    ("light.garden", "Garden light", "off", {}),
    ("sensor.bath_humidity", "Bathroom humidity", "55", {"device_class": "humidity", "unit_of_measurement": "%"}),
    ("vacuum.robot", "Robot vacuum", "docked", {}),
    ("sensor.front_door_last_user", "Front door last user", "", {}),
]
EXTRA_AREA = {"sensor.front_door_last_user": "Entrance", "light.kitchen": "Kitchen", "light.garden": "Driveway", "sensor.bath_humidity": "Bathroom", "vacuum.robot": "Living"}


class DemoClient:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.published: dict = {}
        self.states = [
            {"entity_id": eid, "state": "home" if eid.startswith("device_tracker.") else "off", "last_changed": (now - timedelta(hours=1)).isoformat(),
             "attributes": {"friendly_name": m["name"], "device_class": m.get("device_class")}}
            for eid, m in META.items()
        ]  # fmt: skip
        self.states.append({"entity_id": "calendar.family", "state": "off", "last_changed": now.isoformat(), "attributes": {"friendly_name": "Family calendar"}})
        self.states.append({"entity_id": "input_boolean.night_mode", "state": "off", "last_changed": now.isoformat(), "attributes": {"friendly_name": "Night mode"}})
        for eid, name, st, attrs in EXTRA:
            self.states.append({"entity_id": eid, "state": st, "last_changed": (now - timedelta(hours=2)).isoformat(), "attributes": {"friendly_name": name, **attrs}})

    def get_config(self):
        return {"language": "de"}

    def get_states(self):
        return self.states

    def registries(self):
        areas = sorted({m["area"] for m in META.values() if m.get("area")} | set(EXTRA_AREA.values()) | {"Bathroom"})
        ents = [{"entity_id": eid, "platform": PLATFORM.get(eid, "zha"), "area_id": (m.get("area") or "").lower() or None} for eid, m in META.items()]
        ents += [{"entity_id": eid, "platform": "zha", "area_id": EXTRA_AREA[eid].lower()} for eid, *_ in EXTRA]
        return {
            "entities": ents,
            "devices": [],
            "areas": [{"area_id": a.lower(), "name": a, "floor_id": FLOOR_OF.get(a)} for a in areas],
            "floors": [{"floor_id": "outside", "name": "Outside", "level": -1}, {"floor_id": "ground", "name": "Ground floor", "level": 0}, {"floor_id": "upper", "name": "Upper floor", "level": 1}],
        }

    def get_calendar(self, eid, start, end):
        out = []
        d = self.now - timedelta(days=27)
        while d < self.now:
            if d.weekday() in (0, 2, 4):
                out.append({"summary": "Arbeiten Person B", "start": {"dateTime": d.replace(hour=8).isoformat()}, "end": {"dateTime": d.replace(hour=12).isoformat()}})
            if d.weekday() == 1:
                out.append({"summary": "Tennis Kind A", "start": {"dateTime": d.replace(hour=17).isoformat()}, "end": {"dateTime": d.replace(hour=18).isoformat()}})
            d += timedelta(days=1)
        return out

    def set_state(self, eid, state, attrs):
        self.published[eid] = (state, attrs)


def build(path: str) -> BifrostService:
    sim = household(28, start=datetime.now(UTC) - timedelta(days=29))
    now = datetime.now(UTC)
    client = DemoClient(now)
    store = Store(path)
    svc = BifrostService(client, store, {"shadow_mode": True, "publish_entities": True, "suspicious_entry_level": 2})
    svc.scan()
    for eid, e in svc.snap.entities.items():
        if eid in META or eid == "calendar.family" or eid in EXTRA_AREA:
            e.status = "included"
        if eid == "sensor.bath_humidity":
            e.category, e.role = "climate", "Evidence"
        if eid == "vacuum.robot":
            e.category, e.role = "vehicles", "Noise"
    svc.scan_meta = None
    svc.brain.set_meta({eid: {**META[eid], "integration": PLATFORM.get(eid, "zha")} for eid in META})
    for ev in sim.events:
        store.add_event(datetime.fromisoformat(ev["ts"]), ev["entity_id"], META[ev["entity_id"]]["name"], ev["category"], "Evidence", ev["state"], kind=ev["kind"])
    for d in sim.decisions:
        store.add_decision(datetime.fromisoformat(d["ts"]), d["state"], d["confidence"], ["demo"])
    store.set_value("first_edge", sim.events[0]["ts"])
    store.set_value("first_decision", sim.decisions[0]["ts"])
    svc.brain.people.save({"name": "Person A", "trackers": ["device_tracker.phone_a"], "calendars": ["calendar.family"], "irk": "0123456789abcdef0123456789abcdef"})
    svc.brain.people.save({"name": "Person B", "trackers": ["device_tracker.phone_b"], "calendars": ["calendar.family"], "nfc_user": "Person B"})
    svc.brain.people.save({"name": "Kind A", "may_be_alone": False})
    svc.brain.people.save({"name": "Cleaner", "kind": "visitor", "nfc_user": "Cleaner"})
    svc.learn_job(now)
    svc.evaluate()
    # one suspicious entry at night for the inbox and deviations
    t = now - timedelta(minutes=5)
    svc.brain.detector.model = svc.brain.detector.model or {}
    for eid, sec in (("binary_sensor.motion_outside_front", 0), ("binary_sensor.front_door", 9), ("binary_sensor.motion_hallway", 12)):
        svc.brain.on_edge({"ts": t + timedelta(seconds=sec), "entity_id": eid, "kind": "on", "state": "on"})
    svc.brain.last_extra["state_before"] = "away"
    svc.evaluate()
    svc.brain.inbox.add_exception("binary_sensor.motion_dead", "Animals")
    svc.brain.inbox.deviation("expected_missing", "school_morning", {"goal": "departure", "window": {"from": "07:00", "to": "07:50"}}, now - timedelta(days=1))
    svc.brain.correct("away", "home", now - timedelta(days=3))
    # a few live changes: someone came home through the garage, a timer switched the garden light, a shower
    svc._seed_edges()
    live = [
        ("light.garden", "on", 600, "automation"),
        ("sensor.bath_humidity", "56", 300, "device"),
        ("sensor.bath_humidity", "67", 240, "device"),
        ("vacuum.robot", "cleaning", 200, "device"),
        ("binary_sensor.motion_outside_garage", "on", 40, "device"),
        ("binary_sensor.garage_door", "on", 25, "device"),
        ("binary_sensor.motion_cloakroom", "on", 20, "device"),
        ("light.kitchen", "on", 14, "device"),
        ("binary_sensor.motion_hallway", "on", 9, "device"),
    ]
    svc.set_access_entities(["sensor.front_door_last_user"])
    live += [("sensor.front_door_last_user", "Person B", 3000, "device"), ("sensor.front_door_last_user", "", 2990, "device"), ("sensor.front_door_last_user", "Family code", 1500, "device")]
    live.sort(key=lambda x: -x[2])
    for eid, st, ago, origin in live:
        svc.on_state_changed(eid, st, now - timedelta(seconds=ago), origin=origin)
    return svc
