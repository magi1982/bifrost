"""Learning v0.2 – how reliable is each signal?

Bifrost watches its own decisions. When a decision stays the same for a while with
high confidence (a "confirmed period"), every used signal is checked against it:

- a phone or person tracker agrees when it said "home" during a confirmed Home
  period, or "away" during a confirmed Away period;
- an activity sensor (motion, doors, manual use, media) agrees when it fired during
  Home, and disagrees when it fired while the house was confirmed empty
  (a false alarm, e.g. a pet or a robot).

Trust = Beta(1 + agree, 1 + disagree) mean. Nothing leaves the device.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .engine import AWAY, HOME, Decision, Signal

CONFIRM_MINUTES = 30
CONFIRM_CONFIDENCE = 85
ACTIVITY_CATEGORIES = {"motion", "openings", "manual", "media"}
UNRELIABLE_SCORE = 0.3
MIN_OBSERVATIONS = 5


def trust_score(agree: int, disagree: int) -> float:
    return (1 + agree) / (2 + agree + disagree)


def is_unreliable(counts: tuple[int, int] | None) -> bool:
    if not counts:
        return False
    a, d = counts
    return a + d >= MIN_OBSERVATIONS and trust_score(a, d) < UNRELIABLE_SCORE


def _is_tracker(s: Signal) -> bool:
    return s.entity_id.startswith(("device_tracker.", "person."))


@dataclass
class _Period:
    state: str
    start: datetime
    min_conf: int
    labelled: bool = False


class Learner:
    def __init__(self, store) -> None:  # noqa: ANN001
        self.store = store
        self._last: dict[str, str] = {}
        self._fired: dict[str, int] = {}  # activations within the current period
        self._tracker_ok: dict[str, list[int]] = {}  # [agree, disagree] samples within the period
        self._period: _Period | None = None

    def observe(self, signals: list[Signal], d: Decision, now: datetime) -> None:
        # 1. record state changes as events (timeline + learning input)
        for s in signals:
            prev = self._last.get(s.entity_id)
            if prev is not None and prev != s.state:
                self.store.add_event(now, s.entity_id, s.name, s.category, s.role, s.state)
                if s.category in ACTIVITY_CATEGORIES and s.active:
                    self._fired[s.entity_id] = self._fired.get(s.entity_id, 0) + 1
            self._last[s.entity_id] = s.state

        # 2. track stable periods of the same decision
        p = self._period
        if p is None or p.state != d.state:
            self._period = _Period(d.state, now, d.confidence)
            self._fired, self._tracker_ok = {}, {}
            return
        p.min_conf = min(p.min_conf, d.confidence)
        for s in signals:
            if _is_tracker(s) and s.available:
                v = self._tracker_ok.setdefault(s.entity_id, [0, 0])
                if p.state == AWAY:
                    v[1 if s.active else 0] += 1  # "home" while the house is confirmed empty = wrong
                elif p.state == HOME and s.active:
                    v[0] += 1  # "away" while others are home says nothing, so only count "home"

        # 3. once confirmed, learn from this period exactly once
        if p.labelled or p.state not in (HOME, AWAY) or p.min_conf < CONFIRM_CONFIDENCE:
            return
        if now - p.start < timedelta(minutes=CONFIRM_MINUTES):
            return
        p.labelled = True
        for s in signals:
            if _is_tracker(s):
                a, dis = self._tracker_ok.get(s.entity_id, [0, 0])
                if a or dis:
                    self.store.add_trust(s.entity_id, 1 if a >= dis else 0, 0 if a >= dis else 1)
            elif s.category in ACTIVITY_CATEGORIES and s.role in ("Evidence", "Trigger"):
                fired = self._fired.get(s.entity_id, 0)
                if p.state == AWAY:
                    self.store.add_trust(s.entity_id, 0 if fired else 1, 1 if fired else 0)
                elif fired:
                    self.store.add_trust(s.entity_id, 1, 0)
