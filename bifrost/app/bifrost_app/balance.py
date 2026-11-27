"""Balance and the alarm signal (0.5 / 1.0).

* KPIs: wrong "empty" per month (target 0), share of empty time detected, false suspicions,
  open questions. Labels come from the owner's "That's wrong", hindsight and answered questions.
* Release gate for the signal "house empty confirmed": shadow mode for ≥ 30 days, ≥ 20 departures,
  0 wrong "empty" in the last 30 days, data health ≥ 90 %. Only then – and only if the owner switched
  the option on – Bifrost publishes the confirmation. The alarm system arms itself. Bifrost never disarms.
"""

from __future__ import annotations

from datetime import datetime, timedelta

GATE_DAYS = 30
GATE_DEPARTURES = 20
GATE_HEALTH = 90


def kpis(labels: list[dict], decisions: list[dict], suspicions: list[dict], now: datetime, parse, days: int = 30) -> dict:  # noqa: ANN001
    since = now - timedelta(days=days)
    lab = [x for x in labels if parse(x["ts"]) >= since]
    house = [x for x in lab if not x.get("person")]
    wrong_empty = sum(1 for x in house if x.get("said") == "away" and x.get("actual") in ("home", "asleep"))
    wrong_home = sum(1 for x in house if x.get("said") in ("home", "asleep", "arriving") and x.get("actual") == "away")
    confirmed_empty = sum(1 for x in house if x.get("said") == "away" and x.get("actual") == "away")
    dec = sorted((parse(d["ts"]), d["state"]) for d in decisions if parse(d["ts"]) >= since)
    away_min = 0.0
    for (t, s), nxt in zip(dec, dec[1:] + [(now, None)], strict=False):
        if s == "away":
            away_min += (nxt[0] - t).total_seconds() / 60
    sus = [x for x in suspicions if parse(x["ts"]) >= since]
    false_sus = sum(1 for x in sus if x.get("answer") == "yes")  # "yes, that was us"
    return {
        "days": days,
        "wrong_empty": wrong_empty,
        "wrong_home": wrong_home,
        "confirmed_empty": confirmed_empty,
        "empty_hours": round(away_min / 60, 1),
        "suspicions": len(sus),
        "false_suspicions": false_sus,
    }


def gate(first_day: datetime | None, departures: int, k: dict, health: int, now: datetime, household: int = 1) -> dict:
    checks = [
        {"id": "shadow_days", "ok": bool(first_day) and (now - first_day).days >= GATE_DAYS, "value": (now - first_day).days if first_day else 0, "need": GATE_DAYS},
        {"id": "departures", "ok": departures >= GATE_DEPARTURES, "value": departures, "need": GATE_DEPARTURES},
        {"id": "wrong_empty", "ok": k.get("wrong_empty", 1) == 0, "value": k.get("wrong_empty", 0), "need": 0},
        {"id": "health", "ok": health >= GATE_HEALTH, "value": health, "need": GATE_HEALTH},
        # without the household Bifrost cannot know who might still be inside (children without phones)
        {"id": "household", "ok": household >= 1, "value": household, "need": 1},
    ]
    return {"passed": all(c["ok"] for c in checks), "checks": checks}


def signal(option_on: bool, gate_passed: bool, state: str, confidence: int, guard_ok: bool) -> bool:
    """True only when everything agrees. There is no 'disarm' – by design."""
    return bool(option_on and gate_passed and state == "away" and confidence >= 90 and guard_ok)
