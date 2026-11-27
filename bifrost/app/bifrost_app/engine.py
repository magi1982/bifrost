"""Decision engine v0.1 – explainable rules, no learning yet.

Input: the current states of all signals the user included.
Output: home status, confidence, plain-language reasons, data health.
Shadow mode only matters for actions; v0.1 never triggers anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

HOME, ASLEEP, LEAVING, AWAY, ARRIVING, UNKNOWN = "home", "asleep", "leaving", "away", "arriving", "unknown"
MIN_HEALTH_FOR_AWAY = 60  # below this share of available signals Bifrost refuses to say "empty"

ON_STATES = {"on", "home", "playing", "open", "unlocked", "detected", "occupied"}
OFF_STATES = {"off", "not_home", "away", "idle", "paused", "standby", "closed", "locked", "clear", "unoccupied"}
UNAVAILABLE = {"unavailable", "unknown", "none", ""}


@dataclass
class Signal:
    """One included entity with its current state."""

    entity_id: str
    name: str
    category: str
    role: str
    state: str
    last_changed: datetime

    @property
    def available(self) -> bool:
        return (self.state or "").lower() not in UNAVAILABLE

    @property
    def active(self) -> bool:
        """True if the signal currently says 'something is happening'."""
        s = (self.state or "").lower()
        if s in ON_STATES:
            return True
        if s in OFF_STATES or s in UNAVAILABLE:
            return False
        if self.entity_id.startswith("device_tracker.") or self.entity_id.startswith("person."):
            return False  # a zone name other than home means "not at home"
        try:
            return float(s) > 0
        except ValueError:
            return False


@dataclass
class Settings:
    phone_away_minutes: int = 10
    no_motion_minutes: int = 15
    guest_mode: bool = False
    use_learning: bool = True


@dataclass
class Decision:
    state: str
    confidence: int
    reasons: list[str] = field(default_factory=list)
    data_health: int = 100
    people_home: list[str] = field(default_factory=list)
    last_activity: datetime | None = None
    anomaly: bool = False
    ignored_unreliable: list[str] = field(default_factory=list)

    @property
    def house_empty(self) -> bool:
        return self.state == AWAY


def _minutes(now: datetime, then: datetime) -> float:
    return max(0.0, (now - then).total_seconds() / 60)


def _ago(m: float) -> str:
    return f"{int(m)} min" if m < 120 else f"{m / 60:.1f} h"


def decide(signals: list[Signal], settings: Settings, now: datetime, unreliable: set[str] | None = None, automated: set[str] | None = None) -> Decision:  # noqa: C901
    """Combine all included signals into one explainable decision.

    ``unreliable`` are entity ids that learning found to fire while the house was empty;
    they no longer count as "activity right now" (only when settings.use_learning).
    """
    if settings.guest_mode:
        return Decision(HOME, 95, ["Guest mode is on in Bifrost"], 100, [], now)
    used = [s for s in signals if s.role != "Noise"]
    if not used:
        return Decision(UNKNOWN, 0, ["No signals selected yet – run the scanner in Setup"], 0)

    available = [s for s in used if s.available]
    health = round(100 * len(available) / len(used))
    cap = 0.5 + 0.5 * health / 100  # missing data lowers the maximum confidence

    # 1. Blockers: they make “empty” impossible
    blockers = [s for s in available if s.role == "Blocker" and s.active]
    if blockers:
        sleep = [b for b in blockers if b.category in ("mode_home", "modes") and any(k in (b.entity_id + b.name).lower() for k in ("sleep", "schlaf", "night", "nacht", "bed", "bett"))]
        state = ASLEEP if sleep else HOME
        reasons = [f"{b.name} is active" for b in blockers[:3]]
        return Decision(state, round(95 * cap), reasons, health, [], now)

    # 2. People and their devices
    trackers = [s for s in available if s.category == "devices" and (s.entity_id.startswith("device_tracker.") or s.entity_id.startswith("person."))]
    home = [s for s in trackers if s.active]
    away = [s for s in trackers if not s.active]
    if home:
        recent = [s for s in home if _minutes(now, s.last_changed) < 3]
        trig = [s for s in available if s.role == "Trigger" and _minutes(now, s.last_changed) < 3]
        if recent and trig:
            return Decision(ARRIVING, round(85 * cap), [f"{recent[0].name} just came home", f"{trig[0].name} was used"], health, [s.name for s in home], now)
        return Decision(HOME, round(92 * cap), [f"{s.name} is home" for s in home[:3]], health, [s.name for s in home], now)

    # 3. Recent activity of any kind (motion, manual use, doors)
    activity = [s for s in available if s.role in ("Evidence", "Trigger") and s.category not in ("devices", "calendar")]
    skipped: list[str] = []
    if settings.use_learning and unreliable:
        # learned: these sensors fire while nobody is home (pets, robots, drafts) – they are not activity
        skipped = [s.name for s in activity if s.entity_id in unreliable and s.active]
        activity = [s for s in activity if s.entity_id not in unreliable]
    by_machine: list[str] = []
    if automated:
        # switched by an automation or a learned timer – not a person
        by_machine = [s.name for s in activity if s.entity_id in automated and s.active]
        activity = [s for s in activity if s.entity_id not in automated]
    # Every state change of an activity signal counts – a motion sensor that just switched off saw someone a moment ago
    last_act = max((s.last_changed for s in activity), default=None)
    active_now = [s for s in activity if s.active and s.category in ("motion", "manual", "media")]
    if active_now:
        names = ", ".join(s.name for s in active_now[:2])
        reason = [f"Activity right now: {names}"]
        if trackers:
            reason.append("No known phone is home – maybe a person without a tracked device")
        return Decision(HOME, round(70 * cap), reason, health, [], last_act, anomaly=bool(trackers), ignored_unreliable=skipped)

    if health < MIN_HEALTH_FOR_AWAY:
        return Decision(UNKNOWN, round(30 * cap), [f"Only {health}% of signals are available – too little data to decide"], health, [], last_act)
    if not activity or last_act is None:
        return Decision(UNKNOWN, round(30 * cap), ["No motion, door or manual-use signals selected – Bifrost cannot see activity"], health, [], last_act)
    mins_since_act = _minutes(now, last_act)
    if not trackers:
        # Fail closed: absence of motion alone is never enough for "empty"
        hint = f"No activity for {_ago(mins_since_act)}" if mins_since_act >= settings.no_motion_minutes else "Recent activity is unclear"
        return Decision(UNKNOWN, round(40 * cap), [hint, "No phones or persons selected – add trackers so Bifrost can say “empty”"], health, [], last_act)

    # 4. All trackers away
    left = max(s.last_changed for s in away)
    mins_since_left = _minutes(now, left)
    if mins_since_left < settings.phone_away_minutes or mins_since_act < settings.no_motion_minutes:
        reasons = [f"Last phone left {_ago(mins_since_left)} ago"]
        if mins_since_act < settings.no_motion_minutes:
            reasons.append(f"Last activity {_ago(mins_since_act)} ago – waiting {settings.no_motion_minutes} min")
        return Decision(LEAVING, round(60 * cap), reasons, health, [], last_act, ignored_unreliable=skipped)

    conf = 70 + 20 * min(1.0, mins_since_act / 60) + 9 * min(1.0, len(away) / 3)
    if len(activity) < 2:
        conf = min(conf, 80)  # one activity sensor is not independent confirmation
    reasons = [f"All {len(away)} tracked phones/people are away (last left {_ago(mins_since_left)} ago)", f"No activity for {_ago(mins_since_act)}"]
    if health < 90:
        reasons.append(f"Only {health}% of signals are available – confidence limited")
    if by_machine:
        reasons.append(f"Not counted: {', '.join(by_machine[:2])} – switched by an automation or timer")
    if skipped:
        reasons.append(f"Ignored {', '.join(skipped[:2])} – learned to fire when nobody is home")
    return Decision(AWAY, round(min(99, conf) * cap), reasons, health, [], last_act, ignored_unreliable=skipped)


def parse_time(value: str | None, fallback: datetime) -> datetime:
    """Parse an ISO timestamp from Home Assistant."""
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback


__all__ = ["Decision", "Settings", "Signal", "decide", "parse_time"]
