"""Evidence scale (0.8) – how much each signal says about "somebody is home", learned from hindsight.

Every few minutes of the labelled history (hindsight: certainly home / certainly empty) is a sample.
Per signal Bifrost counts how often it was active in home samples and in empty samples:

    weight = ln( P(active | home) / P(active | empty) )        (Laplace-smoothed)

Trackers get one weight for "home" and one for "away". The live estimate is the prior plus the weights
of everything that is true right now – an explainable sum ("+2.1 hallway motion"), turned into a
probability with the logistic function. Nothing here is hand-tuned and nothing comes from Bifrost's
own decisions. A signal whose weight is ≤ 0 fires as often when the house is empty (animals, robots,
drafts) – it is "not counted" instead of the old trust score.

The model only votes once it has seen enough of both: ``MIN_SAMPLES`` home and empty samples.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from datetime import datetime, timedelta

from .hindsight import EMPTY, HOME

STEP = timedelta(minutes=5)
WINDOW = timedelta(minutes=10)  # a signal counts as "active" this long after it fired
MIN_SAMPLES = 60  # 5 hours of each label before the scale votes
MAX_W = 4.0
PRIOR_CAP = 2.0
CULPRIT_PENALTY = 1.0  # per "That's wrong – this fooled Bifrost"


def _t(v) -> datetime:  # noqa: ANN001
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def _clip(x: float, m: float = MAX_W) -> float:
    return max(-m, min(m, x))


def _activity(events: list[dict], meta: dict[str, dict]) -> dict[str, list[datetime]]:
    """Per signal the moments it said "something happens" (by a person – automations do not count)."""
    out: dict[str, list[datetime]] = {}
    for e in events:
        cat = (meta.get(e["entity_id"]) or {}).get("category") or ""
        if e.get("kind") == "on" and cat in ("motion", "openings", "manual", "media", "mode_home") or e.get("kind") == "access":
            out.setdefault(e["entity_id"], []).append(_t(e["ts"]))
    for v in out.values():
        v.sort()
    return out


def _trackers(events: list[dict]) -> dict[str, tuple[list[datetime], list[str]]]:
    out: dict[str, tuple[list[datetime], list[str]]] = {}
    for e in sorted(events, key=lambda e: str(e["ts"])):
        if e.get("kind") in ("home", "away"):
            ts, ks = out.setdefault(e["entity_id"], ([], []))
            ts.append(_t(e["ts"]))
            ks.append(e["kind"])
    return out


def _active(times: list[datetime], t: datetime) -> bool:
    i = bisect_left(times, t - WINDOW)
    return i < len(times) and times[i] <= t


def _tracker_at(tr: tuple[list[datetime], list[str]], t: datetime) -> str | None:
    i = bisect_left(tr[0], t)
    return tr[1][i - 1] if i else None


def learn(events: list[dict], hind: dict, meta: dict[str, dict]) -> dict:
    """Learn weights from the hindsight segments. Pure."""
    act = _activity(events, meta)
    trk = _trackers(events)
    n = {HOME: 0, EMPTY: 0}
    a: dict[str, dict[str, int]] = {s: {HOME: 0, EMPTY: 0} for s in act}
    tr: dict[str, dict[str, int]] = {s: {"home_" + HOME: 0, "home_" + EMPTY: 0, "away_" + HOME: 0, "away_" + EMPTY: 0} for s in trk}
    for seg in hind.get("segments", []):
        lab = seg["label"]
        if lab not in (HOME, EMPTY):
            continue
        t = seg["start"]
        end = seg["end"]
        if lab == HOME and seg.get("why") == "activity" and end - t < STEP:
            end = t + STEP  # a short burst still is one home sample
        if lab == EMPTY:
            # the edges of an empty stretch are the exit and the entry themselves – they belong to the people
            # walking out and in, not to the empty house
            t, end = t + WINDOW + STEP, end - WINDOW - STEP
        while t <= end:
            n[lab] += 1
            for s, times in act.items():
                if _active(times, t):
                    a[s][lab] += 1
            for s, v in trk.items():
                st = _tracker_at(v, t)
                if st:
                    tr[s][st + "_" + lab] += 1
            t += STEP
    weights: dict[str, dict] = {}
    for s, c in a.items():
        p_home = (c[HOME] + 1) / (n[HOME] + 2)
        p_empty = (c[EMPTY] + 1) / (n[EMPTY] + 2)
        weights[s] = {"active": round(_clip(math.log(p_home / p_empty)), 3), "seen_home": c[HOME], "seen_empty": c[EMPTY]}
    for s, c in tr.items():
        h_home = c["home_" + HOME] + c["away_" + HOME]
        h_empty = c["home_" + EMPTY] + c["away_" + EMPTY]
        w_home = math.log(((c["home_" + HOME] + 1) / (h_home + 2)) / ((c["home_" + EMPTY] + 1) / (h_empty + 2)))
        w_away = math.log(((c["away_" + HOME] + 1) / (h_home + 2)) / ((c["away_" + EMPTY] + 1) / (h_empty + 2)))
        weights[s] = {"home": round(_clip(w_home), 3), "away": round(_clip(w_away), 3), "seen_home": h_home, "seen_empty": h_empty}
    prior = _clip(math.log((n[HOME] + 1) / (n[EMPTY] + 1)), PRIOR_CAP)
    return {"prior": round(prior, 3), "samples": n, "weights": weights, "ready": n[HOME] >= MIN_SAMPLES and n[EMPTY] >= MIN_SAMPLES}


def unreliable(model: dict) -> set[str]:
    """Activity signals that fire at least as often when the house is empty – not counted as activity."""
    return {s for s, w in (model.get("weights") or {}).items() if "active" in w and w["seen_empty"] >= 3 and w["active"] <= 0}


def predict(model: dict, recent: dict[str, datetime], trackers: dict[str, str | None], now: datetime, culprits: dict[str, int] | None = None) -> dict:
    """P(somebody home) now. recent: signal → last time it fired; trackers: entity → "home"/"away"/None."""
    culprits = culprits or {}
    w = model.get("weights") or {}
    total = float(model.get("prior") or 0.0)
    parts: list[dict] = []
    for s, t in recent.items():
        ws = w.get(s)
        if not ws or "active" not in ws or now - t > WINDOW:
            continue
        x = ws["active"] - CULPRIT_PENALTY * culprits.get(s, 0)
        if x > 0:  # a signal that fooled Bifrost or fires when empty never pushes towards "home"
            total += x
            parts.append({"entity_id": s, "weight": round(x, 2), "why": "active"})
    for s, st in trackers.items():
        ws = w.get(s)
        if not ws or st not in ("home", "away") or st not in ws:
            continue
        x = ws[st] - (CULPRIT_PENALTY * culprits.get(s, 0) if st == "home" else 0)
        total += x
        parts.append({"entity_id": s, "weight": round(x, 2), "why": st})
    p = 1 / (1 + math.exp(-max(-30.0, min(30.0, total))))
    parts.sort(key=lambda x: -abs(x["weight"]))
    return {"p_home": round(p, 4), "logit": round(total, 3), "parts": parts[:8], "ready": bool(model.get("ready"))}


def calibration(preds: list[tuple[datetime, float]], hind: dict, bins: int = 5) -> list[dict]:
    """How often was the house really empty when Bifrost said "x % empty"? Uses hindsight as truth."""
    segs = sorted((s["start"], s["end"], s["label"]) for s in hind.get("segments", []) if s["label"] in (HOME, EMPTY))
    starts = [s[0] for s in segs]
    out = [{"from": round(i / bins, 2), "to": round((i + 1) / bins, 2), "n": 0, "empty": 0} for i in range(bins)]
    for t, p_empty in preds:
        i = bisect_left(starts, t + timedelta(microseconds=1)) - 1
        if i < 0 or segs[i][1] < t:
            continue
        b = out[min(bins - 1, int(p_empty * bins))]
        b["n"] += 1
        b["empty"] += segs[i][2] == EMPTY
    for b in out:
        b["share"] = round(b["empty"] / b["n"], 2) if b["n"] else None
    return out


def split_states(p_home: float, sleep_likely: float) -> dict[str, int]:
    """Home / asleep / away in percent (sum 100)."""
    occ = max(0.0, min(1.0, p_home))
    asleep = occ * max(0.0, min(1.0, sleep_likely))
    home = occ - asleep
    away = 1 - occ
    vals = {"home": home * 100, "asleep": asleep * 100, "away": away * 100}
    r = {k: int(v) for k, v in vals.items()}
    rest = 100 - sum(r.values())
    for k in sorted(vals, key=lambda k: -(vals[k] - int(vals[k])))[:rest]:
        r[k] += 1
    return r
