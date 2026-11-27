"""Synthetic household for tests and the demo (example names only).

Doors: front door, garage door. Motion: outside front, hallway (inside front), outside garage,
cloakroom (inside garage door), living room, upstairs. People: Person A (phone), Person B (phone),
Kind A (no phone, never alone). Animals sometimes trigger the hallway sensor while nobody is home.

Realistic trouble (0.8): ``kid_home`` – Kind B (no phone) stays upstairs in a room without a sensor while
both adults leave; the rule engine says "away" (``decisions``) although somebody is inside. ``flap`` – Phone B
drops out of Wi-Fi for two minutes at night. ``SIDES`` is what the house model learns about inside/outside.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

META = {
    "binary_sensor.front_door": {"name": "Front door", "category": "openings", "device_class": "door", "area": "Entrance"},
    "binary_sensor.garage_door": {"name": "Garage door", "category": "openings", "device_class": "door", "area": "Garage"},
    "binary_sensor.terrace_door": {"name": "Terrace door", "category": "openings", "device_class": "door", "area": "Living"},
    "binary_sensor.motion_outside_front": {"name": "Motion outside front", "category": "motion", "device_class": "motion", "area": "Outside"},
    "binary_sensor.motion_hallway": {"name": "Motion hallway", "category": "motion", "device_class": "motion", "area": "Hallway"},
    "binary_sensor.motion_outside_garage": {"name": "Motion outside garage", "category": "motion", "device_class": "motion", "area": "Driveway"},
    "binary_sensor.motion_cloakroom": {"name": "Motion cloakroom", "category": "motion", "device_class": "motion", "area": "Cloakroom"},
    "binary_sensor.motion_living": {"name": "Motion living", "category": "motion", "device_class": "motion", "area": "Living"},
    "binary_sensor.motion_upstairs": {"name": "Motion upstairs", "category": "motion", "device_class": "motion", "area": "Upstairs"},
    "binary_sensor.motion_dead": {"name": "Motion attic", "category": "motion", "device_class": "motion", "area": "Attic"},
    "device_tracker.phone_a": {"name": "Phone A", "category": "devices", "area": None},
    "device_tracker.phone_b": {"name": "Phone B", "category": "devices", "area": None},
}


SIDES = {
    "binary_sensor.motion_outside_front": {"side": "outside"},
    "binary_sensor.motion_outside_garage": {"side": "outside"},
    "binary_sensor.motion_hallway": {"side": "inside"},
    "binary_sensor.motion_cloakroom": {"side": "inside"},
    "binary_sensor.motion_living": {"side": "inside"},
    "binary_sensor.motion_upstairs": {"side": "inside"},
}


class Sim:
    def __init__(self, start: datetime, seed: int = 7) -> None:
        self.t = start
        self.rnd = random.Random(seed)
        self.events: list[dict] = []
        self.decisions: list[dict] = []

    def ev(self, eid: str, kind: str, dt: float = 0.0) -> None:
        self.t += timedelta(seconds=dt)
        self.events.append({"ts": self.t.isoformat(), "entity_id": eid, "kind": kind, "state": kind, "category": META[eid]["category"]})

    def decide(self, state: str) -> None:
        self.decisions.append({"ts": self.t.isoformat(), "state": state, "confidence": 95})

    def walk_in_front(self) -> None:
        self.ev("binary_sensor.motion_outside_front", "on", 0)
        self.ev("binary_sensor.front_door", "on", self.rnd.uniform(5, 20))
        self.ev("binary_sensor.motion_hallway", "on", self.rnd.uniform(1, 4))
        self.ev("binary_sensor.front_door", "off", 10)
        self.ev("binary_sensor.motion_living", "on", self.rnd.uniform(4, 8))

    def walk_in_garage(self) -> None:
        self.ev("binary_sensor.motion_outside_garage", "on", 0)
        self.ev("binary_sensor.garage_door", "on", self.rnd.uniform(15, 40))
        self.ev("binary_sensor.motion_cloakroom", "on", self.rnd.uniform(1, 4))
        self.ev("binary_sensor.garage_door", "off", 10)
        self.ev("binary_sensor.motion_hallway", "on", self.rnd.uniform(3, 6))

    def walk_out_garage(self) -> None:
        self.ev("binary_sensor.motion_living", "on", 0)
        self.ev("binary_sensor.motion_hallway", "on", self.rnd.uniform(120, 300))
        self.ev("binary_sensor.motion_cloakroom", "on", self.rnd.uniform(3, 6))
        self.ev("binary_sensor.garage_door", "on", self.rnd.uniform(5, 15))
        self.ev("binary_sensor.motion_outside_garage", "on", self.rnd.uniform(2, 6))
        self.ev("binary_sensor.garage_door", "off", 8)

    def terrace_from_inside(self) -> None:
        self.ev("binary_sensor.motion_living", "on", 0)
        self.ev("binary_sensor.terrace_door", "on", self.rnd.uniform(5, 20))
        self.ev("binary_sensor.terrace_door", "off", self.rnd.uniform(60, 300))
        self.ev("binary_sensor.motion_living", "on", self.rnd.uniform(2, 10))

    def day(self, animals: bool = False, kid_home: bool = False, flap: bool = False) -> None:  # noqa: C901
        base = self.t.replace(hour=6, minute=30, second=0, microsecond=0)
        self.t = base
        self.decide("home")
        self.ev("binary_sensor.motion_upstairs", "on", 0)
        self.ev("binary_sensor.motion_living", "on", self.rnd.uniform(5, 9))
        self.ev("device_tracker.phone_a", "away", 3600)
        self.walk_out_garage()
        self.ev("device_tracker.phone_b", "away", 900)
        self.walk_out_garage()
        self.decide("away")
        if animals:
            self.ev("binary_sensor.motion_hallway", "on", 3 * 3600)
        if kid_home:
            # Kind B was upstairs all along (no sensor there) and comes down – no door, nobody came in
            self.ev("binary_sensor.motion_living", "on", 2 * 3600)
            self.decide("home")
            self.ev("binary_sensor.motion_living", "on", 300)
        self.t = self.t.replace(hour=12, minute=0) + timedelta(minutes=self.rnd.randint(0, 20))
        self.ev("device_tracker.phone_b", "home", 0)
        self.walk_in_front()
        self.decide("home")
        self.terrace_from_inside()
        self.t = self.t.replace(hour=17, minute=30) + timedelta(minutes=self.rnd.randint(0, 30))
        self.ev("device_tracker.phone_a", "home", 0)
        self.walk_in_garage()
        for _ in range(4):
            self.ev("binary_sensor.motion_living", "on", self.rnd.uniform(60, 600))
            self.ev("binary_sensor.motion_hallway", "on", self.rnd.uniform(3, 7))
        self.t = self.t.replace(hour=22, minute=30)
        self.decide("asleep")
        if flap:
            self.t += timedelta(hours=3)
            self.ev("device_tracker.phone_b", "away", 0)
            self.ev("device_tracker.phone_b", "home", 120)
        self.t = self.t.replace(hour=22, minute=30) + timedelta(hours=8)


def household(days: int = 21, start: datetime | None = None, trouble: bool = False) -> Sim:
    s = Sim(start or datetime(2026, 1, 5, 6, 0, tzinfo=UTC))
    for i in range(days):
        s.day(animals=(i % 4 == 0), kid_home=trouble and i % 7 == 3, flap=trouble and i % 3 == 1)
        s.t = (s.t + timedelta(days=1)).replace(hour=5)
    return s
