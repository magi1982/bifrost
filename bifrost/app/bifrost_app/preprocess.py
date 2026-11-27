"""Event pre-processing (0.4) – turn raw Home Assistant state changes into clean events.

* Only edges count: "on" when a signal starts to say "something happens", "off" when it stops.
  Hold/overrun times of presence detectors therefore do not matter.
* Short flicker (off → on again within the debounce time) is ignored.
* unavailable/unknown is a data gap, never "off".
* Phones/persons only produce "home"/"away" when that meaning really changes.
* Numeric sensors are not turned into events (they would flood the history); they are used elsewhere.
* Duplicate sensors (the same detector reaching HA twice, e.g. via two integrations) are detected
  because their "on" edges always happen together.

Pure Python, no I/O – easy to test.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from .engine import OFF_STATES, ON_STATES, UNAVAILABLE

DEBOUNCE_SECONDS = 2.0
TRACKER_PREFIXES = ("device_tracker.", "person.")

# Typical time blur per integration (seconds): two edges closer than this count as simultaneous.
DEFAULT_BLUR = 1.5
BLUR_BY_INTEGRATION = {
    "loxone": 1.0,
    "zha": 1.5,
    "mqtt": 1.5,
    "shelly": 2.0,
    "hue": 2.0,
    "bthome": 3.0,
    "private_ble_device": 10.0,
    "unifi": 60.0,
    "mobile_app": 30.0,
}

KIND_ON, KIND_OFF, KIND_HOME, KIND_AWAY, KIND_GAP, KIND_CHANGE = "on", "off", "home", "away", "gap", "change"


@dataclass(frozen=True)
class Edge:
    ts: datetime
    entity_id: str
    kind: str
    state: str


def blur_for(integration: str | None) -> float:
    return BLUR_BY_INTEGRATION.get((integration or "").lower(), DEFAULT_BLUR)


def simultaneous(a: datetime, b: datetime, blur_a: float = DEFAULT_BLUR, blur_b: float = DEFAULT_BLUR) -> bool:
    """True if two edges are too close to know their order."""
    return abs((a - b).total_seconds()) <= max(blur_a, blur_b)


def _is_number(value: str) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _meaning(entity_id: str, state: str | None) -> str | None:
    """Map a raw state to on/off/home/away/gap, or None for other values."""
    s = (state or "").strip().lower()
    if s in UNAVAILABLE:
        return KIND_GAP
    if entity_id.startswith(TRACKER_PREFIXES):
        return KIND_HOME if s == "home" else KIND_AWAY
    if s in ON_STATES:
        return KIND_ON
    if s in OFF_STATES:
        return KIND_OFF
    return None


class EdgeFilter:
    """Keeps the last meaning per entity and emits only real edges."""

    def __init__(self, debounce_seconds: float = DEBOUNCE_SECONDS) -> None:
        self.debounce = timedelta(seconds=debounce_seconds)
        self._meaning: dict[str, str] = {}
        self._last_off: dict[str, datetime] = {}
        self._suppressed: set[str] = set()

    def feed(self, entity_id: str, new_state: str | None, ts: datetime) -> list[Edge]:
        meaning = _meaning(entity_id, new_state)
        prev = self._meaning.get(entity_id)
        state = (new_state or "")[:64]

        if meaning is None:
            # other values: keep as a plain change, but never numbers (they would flood the history)
            if _is_number(state) or prev == "value:" + state:
                return []
            self._meaning[entity_id] = "value:" + state
            return [Edge(ts, entity_id, KIND_CHANGE, state)]

        if meaning == prev:
            return []
        self._meaning[entity_id] = meaning

        if meaning == KIND_GAP:
            return [Edge(ts, entity_id, KIND_GAP, state)]
        if prev is None or prev == KIND_GAP:
            # first value or back after a gap: remember it, but it is not an edge
            if meaning == KIND_OFF:
                self._last_off[entity_id] = ts
            return []
        if meaning == KIND_OFF:
            self._last_off[entity_id] = ts
            return [Edge(ts, entity_id, KIND_OFF, state)]
        if meaning == KIND_ON:
            last_off = self._last_off.get(entity_id)
            if last_off is not None and timedelta(0) <= ts - last_off <= self.debounce:
                self._suppressed.add(entity_id)  # flicker: the signal never really stopped
                return []
            return [Edge(ts, entity_id, KIND_ON, state)]
        return [Edge(ts, entity_id, meaning, state)]  # home / away

    def flicker_count(self) -> int:
        return len(self._suppressed)


class DuplicateDetector:
    """Finds pairs of sensors whose "on" edges (almost) always happen together."""

    def __init__(self, window_seconds: float = 1.0, keep: int = 2000) -> None:
        self.window = timedelta(seconds=window_seconds)
        self.keep = keep
        self._recent: list[Edge] = []
        self._count: dict[str, int] = defaultdict(int)
        self._pair: dict[tuple[str, str], int] = defaultdict(int)

    def feed(self, edge: Edge) -> None:
        if edge.kind != KIND_ON:
            return
        self._count[edge.entity_id] += 1
        cutoff = edge.ts - self.window
        self._recent = [e for e in self._recent if e.ts >= cutoff][-self.keep :]
        partners = {e.entity_id for e in self._recent if e.entity_id != edge.entity_id}
        for other in partners:
            key = tuple(sorted((edge.entity_id, other)))
            self._pair[key] += 1  # type: ignore[index]
        self._recent.append(edge)

    def candidates(self, min_events: int = 20, min_ratio: float = 0.95) -> list[dict]:
        out = []
        for (a, b), n in self._pair.items():
            ca, cb = self._count[a], self._count[b]
            if min(ca, cb) < min_events:
                continue
            ra, rb = n / ca, n / cb
            if ra >= min_ratio and rb >= min_ratio:
                out.append({"a": a, "b": b, "together": n, "ratio": round(min(ra, rb), 3)})
        return sorted(out, key=lambda x: -x["together"])
