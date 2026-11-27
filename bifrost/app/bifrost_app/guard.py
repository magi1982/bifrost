"""Guard (Heimdall) – fixed safety rules on top of the rule engine. Never learned, never disarms.

Order of questions every minute:
1. Is somebody certainly home?  A detected entry (recently) → not empty.
2. May the house be empty at all?  Every person accounted for, unknown people = 0, a detected exit
   when the house can see directions, data healthy, Bifrost not just restarted. Otherwise "Unknown".
3. How sure? – left to the engine / patterns.

Also watches entries: an entry from outside that nothing explains while the house was empty or asleep
becomes a suspicion (hint → warning).

0.7: the guard state survives restarts (``to_dict`` / ``from_dict``); after a start Bifrost refuses
"empty" for ``STARTUP_HOLD``; only an exit that no known person explains lowers the unknown counter.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from .engine import ARRIVING, ASLEEP, AWAY, HOME, UNKNOWN, Decision  # noqa: F401

ENTRY_HOLD = timedelta(minutes=15)  # a detected entry keeps the house "not empty" this long
EXPLAIN_BEFORE = timedelta(minutes=3)
EXPLAIN_AFTER = timedelta(minutes=2)
EXIT_EXPLAIN_BEFORE = timedelta(minutes=2)
EXIT_EXPLAIN_AFTER = timedelta(minutes=12)  # a phone leaving the zone takes a while
SUSPICION_HOLD = timedelta(minutes=10)
UNKNOWN_RESET = timedelta(hours=12)  # unknown people are assumed gone after this long without indoor motion
STARTUP_HOLD = timedelta(minutes=10)  # after a (re)start Bifrost first collects before it may say "empty"
STRENGTH_RANK = {"strong": 3, "medium": 2, "weak": 1}
MAX_UNKNOWN = 5


@dataclass
class GuardState:
    unknown_min: int = 0
    last_entry: dict | None = None
    last_exit: dict | None = None
    suspicion: dict | None = None
    last_indoor: datetime | None = None
    log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "unknown_min": self.unknown_min,
            "last_entry": self.last_entry,
            "last_exit": self.last_exit,
            "suspicion": self.suspicion,
            "last_indoor": self.last_indoor.isoformat() if self.last_indoor else None,
            "log": self.log[-50:],
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> GuardState:
        """Restore a saved state. Anything malformed is dropped – but never the unknown counter."""
        if not isinstance(data, dict):
            return cls()
        gs = cls()
        try:
            gs.unknown_min = max(0, min(MAX_UNKNOWN, int(data.get("unknown_min") or 0)))
        except (TypeError, ValueError):
            gs.unknown_min = 1  # unreadable counter: assume somebody unknown, fail closed
        for k in ("last_entry", "last_exit", "suspicion"):
            v = data.get(k)
            setattr(gs, k, v if isinstance(v, dict) else None)
        try:
            gs.last_indoor = datetime.fromisoformat(data["last_indoor"]) if data.get("last_indoor") else None
        except (TypeError, ValueError):
            gs.last_indoor = None
        log = data.get("log")
        gs.log = [x for x in log if isinstance(x, dict)][-50:] if isinstance(log, list) else []
        return gs


def _strength(e: dict) -> int:
    return STRENGTH_RANK.get(e.get("strength") or "weak", 1)


def explain_entry(entry_ts: datetime, identity_events: list[dict], guest_mode: bool, known_explanations: list[dict] | None = None, night: bool = False) -> dict:
    """Find what explains an entry: an identity arriving, NFC, guest mode, a known routine.

    identity_events: [{"ts": datetime, "who": str, "kind": "home"|"nfc"|"away", "strength": "strong|medium|weak"}]
    """
    if guest_mode:
        return {"explained": True, "by": "guest_mode", "who": None, "strength": "strong"}
    cands = [e for e in identity_events if entry_ts - EXPLAIN_BEFORE <= e["ts"] <= entry_ts + EXPLAIN_AFTER and e["kind"] in ("home", "nfc")]
    for k in known_explanations or []:
        cands.append({"ts": entry_ts, "who": k.get("label"), "kind": "known", "strength": k.get("strength", "medium")})
    if not cands:
        return {"explained": False, "by": None, "who": None, "strength": None}
    best = max(cands, key=_strength)
    need = "medium" if night else "weak"  # at night a weak explanation (BLE/Wi-Fi) is not enough
    ok = _strength(best) >= STRENGTH_RANK[need]
    return {"explained": ok, "by": best["kind"], "who": best.get("who"), "strength": best.get("strength"), "too_weak": not ok}


def explain_exit(exit_ts: datetime, identity_events: list[dict]) -> dict:
    """A known person leaving around an exit (their phone leaves the zone) explains it."""
    cands = [e for e in identity_events if e["kind"] == "away" and exit_ts - EXIT_EXPLAIN_BEFORE <= e["ts"] <= exit_ts + EXIT_EXPLAIN_AFTER]
    if not cands:
        return {"explained": False, "by": None, "who": None, "strength": None}
    best = max(cands, key=_strength)
    return {"explained": True, "by": "away", "who": best.get("who"), "strength": best.get("strength")}


def on_opening(gs: GuardState, opening: dict, explanation: dict, state_before: str, now: datetime, level: int) -> dict | None:
    """Update the guard after a classified door opening. Returns a new suspicion or None."""
    res = opening["result"]
    gs.log = (gs.log + [{**opening, "explained": explanation.get("explained")}])[-50:]
    if res == "entry":
        gs.last_entry = {**opening, "at": now.isoformat(), "explanation": explanation}
        if not explanation.get("explained"):
            gs.unknown_min = min(gs.unknown_min + 1, MAX_UNKNOWN)
            if state_before in (AWAY, ASLEEP, UNKNOWN) and level > 0:
                gs.suspicion = {"door": opening["door"], "ts": opening["ts"], "until": (now + SUSPICION_HOLD).isoformat(), "level": level, "too_weak": bool(explanation.get("too_weak"))}
                return gs.suspicion
    elif res == "exit":
        gs.last_exit = {**opening, "at": now.isoformat(), "explanation": explanation}
        # a known person leaving says nothing about the unknown ones – only an unexplained exit lowers the counter
        if gs.unknown_min and not explanation.get("explained"):
            gs.unknown_min -= 1
    return None


def tick(gs: GuardState, now: datetime, indoor_activity: datetime | None) -> None:
    if indoor_activity and (gs.last_indoor is None or indoor_activity > gs.last_indoor):
        gs.last_indoor = indoor_activity
    if gs.suspicion:
        try:
            if datetime.fromisoformat(gs.suspicion["until"]) < now:
                gs.suspicion = None
        except (KeyError, TypeError, ValueError):
            gs.suspicion = None
    if gs.unknown_min and gs.last_indoor and now - gs.last_indoor > UNKNOWN_RESET:
        gs.unknown_min = 0


def _at(v: dict | None) -> datetime | None:
    try:
        return datetime.fromisoformat(v["at"]) if v else None
    except (KeyError, TypeError, ValueError):
        return None


def apply(d: Decision, ledger: dict, gs: GuardState, now: datetime, can_see_direction: bool, min_health: int = 60, warming_up: bool = False) -> tuple[Decision, list[dict]]:
    """Apply the fixed rules. Returns the (possibly corrected) decision and the checklist for the UI."""
    checks: list[dict] = []
    entry_at = _at(gs.last_entry)
    entry_recent = entry_at is not None and now - entry_at <= ENTRY_HOLD
    checks.append({"id": "entry", "ok": not entry_recent, "detail": gs.last_entry["door"] if entry_recent and gs.last_entry else None})

    people_defined = ledger.get("all_away") is not None
    everyone_away = ledger.get("all_away") is not False
    checks.append({"id": "people", "ok": everyone_away, "detail": ", ".join(ledger.get("unclear") or ledger.get("home") or []) or None, "active": people_defined})
    checks.append({"id": "unknown", "ok": gs.unknown_min == 0, "detail": gs.unknown_min or None})
    exit_seen = gs.last_exit is not None and (gs.last_entry is None or str(gs.last_exit.get("ts")) > str(gs.last_entry.get("ts")))
    checks.append({"id": "last_out", "ok": exit_seen or not can_see_direction, "detail": gs.last_exit["door"] if gs.last_exit else None, "active": can_see_direction})
    checks.append({"id": "data", "ok": d.data_health >= min_health, "detail": d.data_health})
    checks.append({"id": "startup", "ok": not warming_up, "detail": None, "active": warming_up})

    if entry_recent and d.state in (AWAY, UNKNOWN) and gs.last_entry:
        return replace(d, state=ARRIVING if d.state == AWAY else HOME, confidence=max(d.confidence, 80), reasons=["Entry detected at " + gs.last_entry["door"], *d.reasons]), checks
    if d.state == AWAY:
        blocking = [c for c in checks if not c["ok"] and c["id"] != "entry"]
        if blocking:
            why = {
                "people": "Not everyone is accounted for: " + (checks[1]["detail"] or "?"),
                "unknown": f"At least {gs.unknown_min} unknown person(s) came in and were not seen leaving",
                "last_out": "No exit through an entrance was detected",
                "data": "Too much data is missing",
                "startup": "Bifrost just started – collecting data before it may say empty",
            }
            return replace(d, state=UNKNOWN, confidence=min(d.confidence, 60), reasons=[why[c["id"]] for c in blocking] + d.reasons), checks
    return d, checks


def failed(d: Decision) -> tuple[Decision, list[dict]]:
    """The guard itself could not run: never let a plain rule decision say "empty" (fail closed)."""
    checks = [{"id": "guard_error", "ok": False, "detail": None, "active": True}]
    if d.state == AWAY:
        d = replace(d, state=UNKNOWN, confidence=min(d.confidence, 40), reasons=["Safety check failed – Bifrost does not say empty", *d.reasons])
    return d, checks


def suspicion_active(gs: GuardState) -> bool:
    return gs.suspicion is not None
