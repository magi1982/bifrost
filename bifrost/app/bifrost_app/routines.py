"""Routines 2.0 (0.6) – many similar chains become one plan.

For every outcome (arrival, departure, bedtime) Bifrost looks at the hour before each occurrence and builds:

* steps chosen by **information value** (lift), not only by frequency – rare but telling steps stay;
* THEN between steps that almost always happen in this order (time span min/typical/max);
* AND for steps that happen together in any order;
* OR for steps that replace each other (one or the other, rarely both);
* OPTIONAL for steps that are usually there;
* COMPANION for identities (phones, tags) that arrive/leave somewhere in the window;
* NOT for "nothing must happen afterwards" (quiet after a departure);
* conditions: weekdays, time window, calendar words.

A plan is kept only if it is seen often enough, is precise, and is better than its best single step.
Facts only: tokens are edges, block events and person events – never opinions.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

WINDOW = timedelta(minutes=60)
MIN_SEEN = 5
MIN_PRECISION = 0.85
REQUIRED_SHARE = 0.85
OPTIONAL_SHARE = 0.5
THEN_SHARE = 0.85
OR_MAX_BOTH = 0.15
MAX_STEPS = 12
MAX_PER_GOAL = 8
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def token_of(e: dict) -> str | None:
    """Facts → tokens. Edges 'on' of sensors, home/away of identities, block/person events."""
    k = e.get("kind")
    eid = e.get("entity_id", "")
    if k in ("on", "home", "away"):
        return f"{eid}:{k}"
    if k in ("block", "person"):
        return f"{k}:{e.get('state')}"
    if k == "event":  # numeric event, e.g. humidity jump in the bathroom
        return f"{eid}:{e.get('state')}"
    return None


def is_companion(tok: str) -> bool:
    return tok.startswith(("device_tracker.", "person.")) or tok.startswith("person:")


def _first_times(seq: list[tuple[datetime, str]], start: datetime, end: datetime) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for t, tok in seq:
        if start <= t <= end and tok not in out:
            out[tok] = t
    return out


def _span(vals: list[float]) -> dict:
    s = sorted(vals)
    q = lambda p: s[min(len(s) - 1, max(0, round(p * (len(s) - 1))))]  # noqa: E731
    return {"min": round(q(0.1)), "typical": round(statistics.median(s)), "max": round(q(0.9))}


def _circ_window(times: list[datetime]) -> dict:
    mins = [t.astimezone().hour * 60 + t.astimezone().minute for t in times]
    ang = [m / 1440 * 2 * math.pi for m in mins]
    mean = math.atan2(sum(math.sin(a) for a in ang), sum(math.cos(a) for a in ang))
    mean_min = round((mean if mean >= 0 else mean + 2 * math.pi) / (2 * math.pi) * 1440) % 1440
    dev = sorted(((m - mean_min + 720) % 1440) - 720 for m in mins)
    lo, hi = dev[max(0, round(0.1 * (len(dev) - 1)))], dev[min(len(dev) - 1, round(0.9 * (len(dev) - 1)))]
    fmt = lambda m: f"{(m % 1440) // 60:02d}:{m % 60:02d}"  # noqa: E731
    return {"typical": fmt(mean_min), "from": fmt(mean_min + lo), "to": fmt(mean_min + hi), "spread_min": round((hi - lo) / 2)}


def mine(events: list[dict], outcomes: list[tuple[str, datetime]], calendar_words: dict[str, list[tuple[datetime, datetime]]] | None = None, owners: dict[str, str] | None = None) -> list[dict]:
    """Build routine plans. owners: token → person name (for the 'who' of a plan)."""
    calendar_words = calendar_words or {}
    owners = owners or {}
    seq = sorted(((datetime.fromisoformat(e["ts"]) if isinstance(e["ts"], str) else e["ts"], tok) for e in events if (tok := token_of(e))), key=lambda x: x[0])
    if not seq:
        return []
    span_days = max(1.0, (seq[-1][0] - seq[0][0]).total_seconds() / 86400)
    base_rate: dict[str, float] = defaultdict(float)  # chance a token appears in a random 60 min window
    per_day: dict[str, set] = defaultdict(set)
    for t, tok in seq:
        per_day[tok].add((t.date(), t.hour))
    for tok, hours in per_day.items():
        base_rate[tok] = min(1.0, len(hours) / (span_days * 24))

    plans: list[dict] = []
    by_goal: dict[str, list[datetime]] = defaultdict(list)
    for goal, t in outcomes:
        by_goal[goal].append(t)
    for goal, times in by_goal.items():
        if len(times) < MIN_SEEN:
            continue
        occ = [_first_times(seq, t - WINDOW, t) for t in times]
        n = len(occ)
        present: dict[str, int] = defaultdict(int)
        for o in occ:
            for tok in o:
                present[tok] += 1
        scored = []
        for tok, c in present.items():
            share = c / n
            lift = share / max(base_rate.get(tok, 0.01), 0.01)
            if share >= OPTIONAL_SHARE and lift >= 1.5:
                scored.append((share * math.log(1 + lift), tok, share))
        scored.sort(reverse=True)
        chosen = [tok for _, tok, _ in scored[:MAX_STEPS]]
        if not chosen:
            continue
        share = {tok: present[tok] / n for tok in chosen}
        # OR groups: pairs that rarely happen together but together cover most occurrences
        or_groups: list[list[str]] = []
        used: set[str] = set()
        for a in chosen:
            if a in used or is_companion(a):
                continue
            for b in chosen:
                if b == a or b in used or is_companion(b):
                    continue
                both = sum(1 for o in occ if a in o and b in o) / n
                either = sum(1 for o in occ if a in o or b in o) / n
                if both <= OR_MAX_BOTH and either >= REQUIRED_SHARE and share[a] < REQUIRED_SHARE and share[b] < REQUIRED_SHARE:
                    or_groups.append([a, b])
                    used |= {a, b}
                    break
        singles = [t for t in chosen if t not in used and not is_companion(t)]
        companions = [t for t in chosen if is_companion(t)]
        # order singles and OR groups by median offset to the outcome
        units: list[dict] = []
        for t in singles:
            offs = [(times[i] - o[t]).total_seconds() / 60 for i, o in enumerate(occ) if t in o]
            units.append({"kind": "step" if share[t] >= REQUIRED_SHARE else "optional", "tokens": [t], "offset": statistics.median(offs), "share": share[t]})
        for g in or_groups:
            offs = [(times[i] - o[x]).total_seconds() / 60 for i, o in enumerate(occ) for x in g if x in o]
            units.append({"kind": "or", "tokens": g, "offset": statistics.median(offs), "share": sum(1 for o in occ if any(x in o for x in g)) / n})
        units.sort(key=lambda u: -u["offset"])
        # AND: neighbouring required units whose order is not stable → merge
        steps: list[dict] = []
        for u in units:
            if steps and u["kind"] == "step" and steps[-1]["kind"] in ("step", "and"):
                prev_tokens = steps[-1]["tokens"]
                a, b = prev_tokens[-1], u["tokens"][0]
                both = [o for o in occ if a in o and b in o]
                if both and sum(1 for o in both if o[a] <= o[b]) / len(both) < THEN_SHARE:
                    steps[-1] = {"kind": "and", "tokens": prev_tokens + [b], "share": min(steps[-1]["share"], u["share"])}
                    continue
            steps.append(u)
        # time spans between consecutive units
        for i in range(1, len(steps)):
            gaps = []
            for o in occ:
                pa = [o[x] for x in steps[i - 1]["tokens"] if x in o]
                pb = [o[x] for x in steps[i]["tokens"] if x in o]
                if pa and pb and min(pb) >= max(pa):
                    gaps.append((min(pb) - max(pa)).total_seconds())
            if gaps:
                steps[i]["span"] = _span(gaps)
        comp = []
        for t in companions:
            offs = [(o[t] - times[i]).total_seconds() / 60 for i, o in enumerate(occ) if t in o]
            comp.append({"token": t, "share": round(share[t], 2), "window": {"from": round(min(offs)), "to": round(max(offs))}})
        # NOT: quiet after a departure
        not_step = None
        if goal == "departure":
            quiet = sum(1 for t in times if not any(t < x <= t + timedelta(minutes=15) and tok.endswith(":on") for x, tok in seq)) / n
            if quiet >= REQUIRED_SHARE:
                not_step = {"kind": "not", "what": "motion", "minutes": 15, "share": round(quiet, 2)}
        # conditions
        wd = defaultdict(int)
        for t in times:
            wd[t.astimezone().weekday()] += 1
        weeks = max(1.0, span_days / 7)
        days = [WEEKDAYS[d] for d in range(7) if wd[d] / weeks >= 0.5]
        conds = {"weekdays": days, "time": _circ_window(times)}
        cal = []
        for word, spans in calendar_words.items():
            hits = sum(1 for t in times if any(a <= t <= b for a, b in spans))
            if hits >= MIN_SEEN and hits / n >= 0.6:
                cal.append({"word": word, "share": round(hits / n, 2)})
        if cal:
            conds["calendar"] = cal
        # precision of the required core: how often did the core happen and was followed by the goal?
        core = [s for s in steps if s["kind"] in ("step", "and", "or")]
        prec, seen = _precision(seq, core, times)
        best_single = max((present[t] / max(1, sum(1 for _, x in seq if x == t)) for t in chosen), default=0)
        if seen < MIN_SEEN or prec < MIN_PRECISION or (prec + 0.01 < best_single and len(core) > 1):  # worse than one step alone
            continue
        tokens = sorted({x for s in steps for x in s["tokens"]} | {c["token"] for c in comp})
        pid = "r" + hashlib.sha1((goal + "|" + "|".join(tokens)).encode(), usedforsecurity=False).hexdigest()[:8]
        who = sorted({owners[t] for t in tokens if t in owners})
        plans.append(
            {
                "id": pid,
                "type": "routine",
                "goal": goal,
                "seen": seen,
                "occurrences": n,
                "precision": round(prec, 3),
                "steps": steps,
                "companions": comp,
                "not": not_step,
                "conditions": conds,
                "who": who or ["family"],
                "tokens": tokens,
            }
        )
    return hygiene(plans)


def _precision(seq: list[tuple[datetime, str]], core: list[dict], outcomes: list[datetime]) -> tuple[float, int]:
    """Replay history: every time the core chain completed, did the goal follow within 30 min?"""
    if not core:
        return 0.0, 0
    hits = fires = 0
    idx, last = 0, None
    for t, tok in seq:
        if last and t - last > WINDOW:
            idx, last = 0, None
        if tok in core[idx]["tokens"]:
            idx, last = idx + 1, t
            if idx == len(core):
                fires += 1
                if any(t <= o <= t + timedelta(minutes=30) for o in outcomes):
                    hits += 1
                idx, last = 0, None
    return (hits / fires if fires else 0.0), fires


def hygiene(plans: list[dict]) -> list[dict]:
    """Merge near-duplicates, keep the best per goal within the budget."""
    plans = sorted(plans, key=lambda p: -(p["precision"] * math.log(1 + p["seen"])))
    kept: list[dict] = []
    for p in plans:
        ts = set(p["tokens"])
        if any(k["goal"] == p["goal"] and len(ts & set(k["tokens"])) / max(1, len(ts | set(k["tokens"]))) >= 0.8 for k in kept):
            continue
        if sum(1 for k in kept if k["goal"] == p["goal"]) >= MAX_PER_GOAL:
            continue
        kept.append(p)
    return kept


def progress(plan: dict, recent: list[tuple[datetime, str]], now: datetime) -> float:
    """Share of the core already done (in order) within the last hour – for early detection."""
    core = [s for s in plan["steps"] if s["kind"] in ("step", "and", "or")]
    if not core:
        return 0.0
    idx = 0
    for t, tok in sorted(recent):
        if now - t > WINDOW:
            continue
        if idx < len(core) and tok in core[idx]["tokens"]:
            idx += 1
    return idx / len(core)
