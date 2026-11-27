"""Signal value (0.10) – which signals help to tell "home" from "empty", and which bring nothing.

Bifrost judges every used signal by itself, from what it already learned – no setting needed:

* **information** – the evidence weight learned from hindsight (evidence.py): how much more often the signal
  fires when somebody is home than when the house is empty. Near zero = it says nothing.
* **activity** – changes per day; a signal that hardly ever changes cannot tell "right now".
* **hold** – how long it typically stays "on". A presence *zone* from another system (e.g. a summary of several
  detectors) stays on long after the last person left: it is slow and says little about the present.
* **duplicate** – always fires together with another signal (preprocess.DuplicateDetector): one is enough.
* **doctor** – dead or often unavailable (blocks.sensor_doctor).

Verdicts: valuable · little · nothing · slow · too_few. Bifrost only *suggests* switching a signal off –
the owner decides. Signals judged "nothing" or "slow" are archived in the House tab (shown on request).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

VALUABLE, LITTLE, NOTHING, SLOW, TOO_FEW = "valuable", "little", "nothing", "slow", "too_few"
ARCHIVED = (NOTHING, SLOW)
SLOW_HOLD = 600  # s: a motion signal that typically stays on ≥ 10 minutes is a slow zone
MIN_CHANGES_PER_DAY = 0.2
MIN_DAYS = 7
MIN_SEEN = 10  # evidence samples before the weight is trusted
W_VALUABLE, W_LITTLE = 1.0, 0.3
JUDGED = ("motion", "openings", "manual", "media", "devices", "access", "climate", "energy")


def _t(v) -> datetime:  # noqa: ANN001
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def judge(events: list[dict], meta: dict[str, dict], evidence_model: dict | None, doctor: list[dict] | None, duplicates: list[dict] | None, days: float) -> dict[str, dict]:  # noqa: C901
    """Verdict per signal: {"verdict", "reason", "changes_per_day", "hold_s", "weight"}."""
    weights = (evidence_model or {}).get("weights") or {}
    ready = bool((evidence_model or {}).get("ready"))
    problems = {p["entity_id"]: p.get("problem") for p in doctor or []}
    dup_of = {d["b"]: d["a"] for d in duplicates or []}  # the second of a pair is the one to drop
    changes: dict[str, int] = defaultdict(int)
    holds: dict[str, list[float]] = defaultdict(list)
    on_since: dict[str, datetime] = {}
    for e in sorted(events, key=lambda e: str(e["ts"])):
        k, eid = e.get("kind"), e["entity_id"]
        if k in ("on", "off", "home", "away", "access", "event", "auto"):
            changes[eid] += 1
        if k == "on":
            on_since[eid] = _t(e["ts"])
        elif k == "off" and eid in on_since:
            holds[eid].append((_t(e["ts"]) - on_since.pop(eid)).total_seconds())
    out: dict[str, dict] = {}
    for eid, m in meta.items():
        cat = m.get("category") or ""
        if cat not in JUDGED:
            continue
        cpd = changes.get(eid, 0) / max(days, 1e-9) if days else 0.0
        hold = statistics.median(holds[eid]) if len(holds.get(eid, [])) >= 5 else None
        w = weights.get(eid) or {}
        weight = w.get("active") if "active" in w else (abs(w["home"] - w["away"]) / 2 if "home" in w and "away" in w else None)
        seen = int(w.get("seen_home", 0)) + int(w.get("seen_empty", 0))
        row = {"changes_per_day": round(cpd, 2), "hold_s": round(hold) if hold is not None else None, "weight": weight}
        if problems.get(eid) == "dead":
            v, why = NOTHING, "dead"
        elif eid in dup_of:
            v, why = NOTHING, "duplicate"
        elif days >= MIN_DAYS and cpd < MIN_CHANGES_PER_DAY:
            v, why = NOTHING, "hardly_changes"
        elif cat == "motion" and hold is not None and hold >= SLOW_HOLD:
            v, why = SLOW, "long_hold"
        elif ready and weight is not None and seen >= MIN_SEEN:
            if weight >= W_VALUABLE:
                v, why = VALUABLE, "informative"
            elif weight >= W_LITTLE:
                v, why = LITTLE, "weak_information"
            else:
                v, why = NOTHING, "no_information"
        else:
            v, why = TOO_FEW, "learning"
        out[eid] = {"verdict": v, "reason": why, **row, **({"duplicate_of": dup_of[eid]} if eid in dup_of else {})}
    return out


def counts(judged: dict[str, dict]) -> dict[str, int]:
    c = {k: 0 for k in (VALUABLE, LITTLE, NOTHING, SLOW, TOO_FEW)}
    for v in judged.values():
        c[v["verdict"]] = c.get(v["verdict"], 0) + 1
    return c
