"""Live view of the house: who or what changed what, right now, per floor and area.

* ``origin_of`` reads Home Assistant's context: a user id means someone used an app or the
  dashboard, a parent id means an automation or script, neither means the device itself
  (a physical switch, a sensor – or another system such as Loxone).
* ``OriginLearner`` learns device changes that happen at the same time every day (timers in
  Loxone or in the device) and treats them as "scheduled", not as a person.
* ``NumericEvents`` turns slow values into events: humidity jump (shower), CO₂ rise (people in
  the room), power spike above base load (appliance started), water starts flowing.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# origins
PERSON = "person"  # physical switch / button – a person at home
APP = "app"  # app or dashboard – a person, maybe not at home
AUTOMATION = "automation"
SCHEDULED = "scheduled"  # learned: same time every day without context
SENSOR = "sensor"  # sensors report, nobody "switched" them

# categories in which a change is an action (somebody or something switched it)
ACTION_CATEGORIES = {"manual", "media", "energy", "mode_home", "mode_away"}

SCHEDULE_WINDOW_MIN = 5
SCHEDULE_MIN_DAYS = 5
SCHEDULE_LOOKBACK_DAYS = 14


def origin_of(msg: dict) -> str:
    """Raw origin from a state_changed message: app, automation or device."""
    ctx = (((msg.get("event") or {}).get("data") or {}).get("new_state") or {}).get("context") or (msg.get("event") or {}).get("context") or {}
    if ctx.get("parent_id"):
        return AUTOMATION
    if ctx.get("user_id"):
        return APP
    return "device"


class OriginLearner:
    """Remembers at which minute of the day a device switched itself on."""

    def __init__(self) -> None:
        self._seen: dict[str, deque[tuple[str, int]]] = defaultdict(lambda: deque(maxlen=120))

    def record(self, entity_id: str, ts: datetime) -> None:
        local = ts.astimezone()
        self._seen[entity_id].append((local.date().isoformat(), local.hour * 60 + local.minute))

    def scheduled(self, entity_id: str, ts: datetime) -> bool:
        local = ts.astimezone()
        minute = local.hour * 60 + local.minute
        since = (local.date() - timedelta(days=SCHEDULE_LOOKBACK_DAYS)).isoformat()
        today = local.date().isoformat()
        days = set()
        for day, m in self._seen.get(entity_id, ()):
            diff = min(abs(m - minute), 1440 - abs(m - minute))
            if since <= day < today and diff <= SCHEDULE_WINDOW_MIN:
                days.add(day)
        return len(days) >= SCHEDULE_MIN_DAYS

    def dump(self) -> dict:
        return {k: list(v) for k, v in self._seen.items()}

    def load(self, data: dict) -> None:
        for k, v in (data or {}).items():
            if isinstance(k, str) and isinstance(v, list):
                self._seen[k].extend((str(a), int(b)) for a, b in v[-120:] if isinstance(b, int | float))


def classify_origin(raw: str, category: str, scheduled: bool) -> str:
    """Final origin shown and used: sensor, person, app, automation or scheduled."""
    if category not in ACTION_CATEGORIES:
        return SENSOR
    if raw == AUTOMATION:
        return AUTOMATION
    if raw == APP:
        return APP
    return SCHEDULED if scheduled else PERSON


def _kind(device_class: str | None, unit: str | None, entity_id: str) -> str | None:
    dc, u, e = (device_class or "").lower(), (unit or "").lower(), entity_id.lower()
    if dc == "humidity" or (u == "%" and ("humid" in e or "feucht" in e)):
        return "humidity"
    if dc == "carbon_dioxide" or u == "ppm":
        return "co2"
    if dc == "power" or u in ("w", "kw"):
        return "power"
    if dc in ("volume_flow_rate",) or u in ("l/min", "m³/h", "l/h"):
        return "water"
    return None


@dataclass
class _Track:
    kind: str
    values: deque = field(default_factory=lambda: deque(maxlen=240))  # (ts, value)
    last_event: datetime | None = None


THRESHOLDS = {"humidity": (8.0, 10), "co2": (150.0, 20), "power": (300.0, 60), "water": (0.5, 5)}
EVENT_NAME = {"humidity": "humidity_jump", "co2": "co2_rise", "power": "power_spike", "water": "water_flow"}
COOLDOWN = timedelta(minutes=15)


class NumericEvents:
    """Detects meaningful jumps in slow numeric values."""

    def __init__(self) -> None:
        self._t: dict[str, _Track] = {}

    def feed(self, entity_id: str, value: str | None, ts: datetime, device_class: str | None = None, unit: str | None = None) -> str | None:
        try:
            v = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        kind = _kind(device_class, unit, entity_id)
        if kind is None:
            return None
        if kind == "power" and (unit or "").lower() == "kw":
            v *= 1000
        tr = self._t.setdefault(entity_id, _Track(kind))
        delta, minutes = THRESHOLDS[kind]
        window = [x for t, x in tr.values if ts - t <= timedelta(minutes=minutes)]
        tr.values.append((ts, v))
        if not window:
            return None
        base = min(window)
        if v - base >= delta and (tr.last_event is None or ts - tr.last_event >= COOLDOWN):
            tr.last_event = ts
            return EVENT_NAME[kind]
        return None

    def trend(self, entity_id: str) -> dict | None:
        tr = self._t.get(entity_id)
        if not tr or len(tr.values) < 2:
            return None
        (_, a), (_, b) = tr.values[max(0, len(tr.values) - 6)], tr.values[-1]
        delta, _ = THRESHOLDS[tr.kind]
        d = b - a
        return {"kind": tr.kind, "value": round(b, 1), "dir": "up" if d >= delta / 4 else "down" if d <= -delta / 4 else "flat"}


@dataclass
class LiveSignal:
    ts: datetime
    state: str
    origin: str
    event: str = ""


class LiveBoard:
    """Last change per entity and the most recent chain of events."""

    def __init__(self) -> None:
        self.last: dict[str, LiveSignal] = {}
        self.recent: deque[dict] = deque(maxlen=60)

    def note(self, entity_id: str, ts: datetime, state: str, origin: str, event: str = "") -> None:
        self.last[entity_id] = LiveSignal(ts, state, origin, event)
        self.recent.append({"ts": ts, "entity_id": entity_id, "state": state, "origin": origin, "event": event})

    def last_path(self, now: datetime, gap: timedelta = timedelta(minutes=2), limit: int = 6) -> list[dict]:
        """The latest burst of events that follow each other with less than ``gap`` in between."""
        out: list[dict] = []
        prev: datetime | None = None
        for ev in reversed(self.recent):
            if ev["origin"] in (AUTOMATION, SCHEDULED):
                continue
            if prev is not None and prev - ev["ts"] > gap:
                break
            if out and out[-1]["entity_id"] == ev["entity_id"]:
                prev = ev["ts"]
                continue
            out.append(ev)
            prev = ev["ts"]
            if len(out) >= limit:
                break
        if out and now - out[0]["ts"] > timedelta(minutes=30):
            return []
        return list(reversed(out))

    def automated(self, within: timedelta, now: datetime) -> set[str]:
        """Entities whose last change came from an automation or a schedule."""
        return {e for e, s in self.last.items() if s.origin in (AUTOMATION, SCHEDULED) and now - s.ts <= within}
