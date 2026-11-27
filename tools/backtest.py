"""Backtest on your own data – locally, nothing leaves the machine.

Runs the hindsight labeller over the events stored in a Bifrost database and compares it with the
decisions Bifrost made at the time: how often did it say "empty" while somebody was certainly inside,
how much of the certainly-empty time did it recognise, and how well do its percentages match reality.

    python3 tools/backtest.py /path/to/bifrost.db [days]

Copy the database from the app's /data folder (e.g. via the Samba or SSH app). The report contains
only counts and times, never names or titles.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bifrost" / "app"))

from bifrost_app import evidence, hindsight  # noqa: E402
from bifrost_app.store import Store  # noqa: E402


def run(db: str, days: int = 56, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    store = Store(db)
    since = now - timedelta(days=days)
    events = list(reversed(store.events_since(since, limit=500000)))
    decisions = store.decisions_since(since)
    meta = {e["entity_id"]: {"category": e.get("category") or ""} for e in events}
    house = store.get_obj("model", "house") or {}
    exceptions = {x.get("sensor") for x in store.list_objs("exception") if x.get("sensor")}
    labels = [x for x in store.list_objs("label") if "said" in x]
    hind = hindsight.label(events, meta, house.get("sides", {}), exceptions, labels)
    wrong = hindsight.wrong_empty(hind, decisions, datetime.fromisoformat)
    # share of certainly-empty time Bifrost also called empty
    dec = sorted((datetime.fromisoformat(d["ts"]), d["state"]) for d in decisions)
    found = total = 0.0
    for seg in hind["segments"]:
        if seg["label"] != hindsight.EMPTY:
            continue
        total += (seg["end"] - seg["start"]).total_seconds()
        for i, (t, st) in enumerate(dec):
            nxt = dec[i + 1][0] if i + 1 < len(dec) else now
            if st == "away":
                lo, hi = max(t, seg["start"]), min(nxt, seg["end"])
                if hi > lo:
                    found += (hi - lo).total_seconds()
    preds = []
    for i in range(days):
        for row in (store.get_obj("pred", (now - timedelta(days=i)).date().isoformat()) or {}).get("rows", []):
            preds.append((datetime.fromisoformat(row[0]), float(row[1])))
    store.close()
    return {
        "days": days,
        "events": len(events),
        "hindsight_hours": hind["stats"],
        "departures": len(hind["departures"]),
        "wrong_empty": len(wrong),
        "wrong_empty_moments": wrong[:20],
        "empty_time_recognised": round(found / total, 2) if total else None,
        "calibration": evidence.calibration(preds, hind),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    print(json.dumps(run(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 56), indent=1))
