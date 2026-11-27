"""Timing (0.6) – when does each person usually come home or leave, and how long do states last?

Circular statistics on the 24 h clock per person and weekday ("usually 17:35 ± 20 min").
Feeds "arriving soon", the expected return and the guard ("somebody is expected – do not suggest arming").
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

MIN_OBS = 3


def _circ(minutes: list[int]) -> tuple[int, int]:
    ang = [m / 1440 * 2 * math.pi for m in minutes]
    mean = math.atan2(sum(math.sin(a) for a in ang), sum(math.cos(a) for a in ang))
    mean_min = round((mean if mean >= 0 else mean + 2 * math.pi) / (2 * math.pi) * 1440) % 1440
    dev = [abs(((m - mean_min + 720) % 1440) - 720) for m in minutes]
    return mean_min, round(statistics.median(dev)) if dev else 0


def fmt(m: int) -> str:
    return f"{(m % 1440) // 60:02d}:{m % 60:02d}"


def learn(person_events: list[tuple[datetime, str, str]]) -> dict:
    """person_events: (ts, person, 'home'|'away'). Returns per person and weekday typical times."""
    arr: dict[tuple[str, int], list[int]] = defaultdict(list)
    dep: dict[tuple[str, int], list[int]] = defaultdict(list)
    for ts, p, kind in person_events:
        lt = ts.astimezone()
        (arr if kind == "home" else dep)[(p, lt.weekday())].append(lt.hour * 60 + lt.minute)
    out: dict[str, dict] = defaultdict(lambda: {"arrive": {}, "leave": {}})
    for src, key in ((arr, "arrive"), (dep, "leave")):
        for (p, wd), mins in src.items():
            if len(mins) >= MIN_OBS:
                m, spread = _circ(mins)
                out[p][key][wd] = {"typical": fmt(m), "minute": m, "spread": max(10, spread), "n": len(mins)}
    return dict(out)


def durations(decisions: list[dict], parse) -> dict:  # noqa: ANN001
    """Typical duration (minutes) of each state."""
    dur: dict[str, list[float]] = defaultdict(list)
    prev = None
    for d in sorted(decisions, key=lambda x: x["ts"]):
        t = parse(d["ts"])
        if prev and prev[1] != d["state"]:
            dur[prev[1]].append((t - prev[0]).total_seconds() / 60)
            prev = (t, d["state"])
        elif prev is None:
            prev = (t, d["state"])
    return {s: {"typical": round(statistics.median(v)), "n": len(v)} for s, v in dur.items() if len(v) >= MIN_OBS}


def expected(model: dict, person: str, now: datetime, kind: str = "arrive") -> dict | None:
    """Next typical time today for this person, if any."""
    lt = now.astimezone()
    slot = model.get(person, {}).get(kind, {}).get(lt.weekday())
    if not slot:
        return None
    mid = lt.replace(hour=0, minute=0, second=0, microsecond=0)
    at = mid + timedelta(minutes=slot["minute"])
    return {"at": at, "from": at - timedelta(minutes=slot["spread"]), "to": at + timedelta(minutes=slot["spread"]), "typical": slot["typical"], "n": slot["n"]}


def soon(model: dict, person: str, now: datetime, kind: str = "arrive", horizon: int = 15) -> bool:
    e = expected(model, person, now, kind)
    return bool(e) and e["from"] - timedelta(minutes=horizon) <= now <= e["to"]
