"""Calendar learning v0.3 – which calendar entries mean "nobody is home"?

For every calendar Bifrost uses, it reads the entries of the last weeks from Home Assistant
and compares them with its own decisions: during how much of each entry was the house Away?

Privacy: full titles are never stored. Titles are split into lower-case keywords
(at least 4 letters, common filler words removed); only these keywords and their counts are
kept locally. Birthday calendars are ignored by the scanner. Learning can be switched off.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

STOP = {
    "with",
    "from",
    "this",
    "that",
    "have",
    "und",
    "mit",
    "der",
    "die",
    "das",
    "den",
    "dem",
    "des",
    "ein",
    "eine",
    "einen",
    "für",
    "fuer",
    "von",
    "bei",
    "beim",
    "zum",
    "zur",
    "uhr",
    "termin",
    "meeting",
    "call",
    "online",
    "teams",
}
MIN_OBS = 3  # entries per keyword before Bifrost trusts it
AWAY_SHARE = 0.85


def keywords(title: str) -> set[str]:
    words = re.findall(r"[a-zäöüß]{4,}", (title or "").lower())
    return {w for w in words if w not in STOP}


def _parse_dt(v: dict | str | None, parse) -> datetime | None:  # noqa: ANN001
    if isinstance(v, dict):
        v = v.get("dateTime") or v.get("date")
    if not v:
        return None
    if len(v) == 10:  # all-day entries
        v += "T00:00:00+00:00"
    return parse(v)


def away_share(start: datetime, end: datetime, decisions: list[dict], parse) -> float | None:  # noqa: ANN001
    """Share of [start, end) during which Bifrost said Away (decisions sorted by ts)."""
    if end <= start:
        return None
    total = away = 0.0
    for i, d in enumerate(decisions):
        t0 = max(parse(d["ts"]), start)
        t1 = min(parse(decisions[i + 1]["ts"]) if i + 1 < len(decisions) else end, end)
        if t1 <= t0:
            continue
        sec = (t1 - t0).total_seconds()
        total += sec
        if d["state"] == "away":
            away += sec
    return away / total if total > 0 else None


def learn(calendar_id: str, entries: list[dict], decisions: list[dict], parse) -> dict:  # noqa: ANN001
    """Return per-keyword statistics: {keyword: [entries, entries mostly away]} plus overall numbers."""
    stats: dict[str, list[int]] = {}
    n = away_n = 0
    decisions = sorted(decisions, key=lambda d: d["ts"])
    for e in entries:
        st, en = _parse_dt(e.get("start"), parse), _parse_dt(e.get("end"), parse)
        if not st or not en or en - st > timedelta(days=2):
            continue  # skip multi-day entries such as holidays spanning weeks
        share = away_share(st, en, decisions, parse)
        if share is None:
            continue
        mostly_away = share >= 0.5
        n += 1
        away_n += mostly_away
        for k in keywords(e.get("summary", "")):
            v = stats.setdefault(k, [0, 0])
            v[0] += 1
            v[1] += mostly_away
    return {"calendar": calendar_id, "entries": n, "away": away_n, "keywords": stats}


def insights(stat: dict) -> list[dict]:
    """Keywords that reliably mean away (or home), most observations first."""
    out = []
    for k, (n, a) in stat.get("keywords", {}).items():
        if n >= MIN_OBS:
            share = a / n
            out.append({"keyword": k, "entries": n, "away_share": round(100 * share), "means_away": share >= AWAY_SHARE})
    return sorted(out, key=lambda x: (-x["means_away"], -x["entries"]))[:20]


def active_hint(active_titles: list[tuple[str, str]], learned: dict[str, dict]) -> list[str]:
    """Reasons for current calendar entries whose keywords usually mean Away. Titles are not echoed."""
    hints = []
    for cal_id, title in active_titles:
        st = learned.get(cal_id)
        if not st:
            continue
        kw = st.get("keywords", {})
        for k in sorted(keywords(title), key=lambda w: (-kw.get(w, (0, 0))[0], w)):  # deterministic: most seen first
            n, a = kw.get(k, (0, 0))
            if n >= MIN_OBS and a / n >= AWAY_SHARE:
                hints.append(f"Calendar entry with “{k}” – usually away ({round(100 * a / n)} % of {n})")
                break
    return hints


def window(now: datetime, days: int = 42) -> tuple[datetime, datetime]:
    return now - timedelta(days=days), now
