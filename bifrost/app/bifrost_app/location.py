"""Where in the house (0.7) – rough place of a person, learned, never hard-coded.

* **BLE fingerprints:** signal strength (RSSI) per scanner forms a vector. Bifrost labels moments whose
  place is known from facts (an entry block = just inside, motion only in one room, garden block) and
  learns one centroid per place. A new sample is assigned to the nearest centroid – or "unknown".
* **Wi-Fi access point:** the access point a phone is connected to gives a coarse place; the owner maps
  access points to places once (suggested from the learned map).
* **CO₂ breathing:** a steadily falling CO₂ level with nobody moving supports "empty", a rising level
  while "empty" is a contradiction. Only a hint, never a proof.
* **Floor plan:** optional picture under the learned house map (PNG/JPEG only, size-limited, local).
"""

from __future__ import annotations

import base64
import math
import statistics
from collections import defaultdict
from datetime import datetime

MIN_SAMPLES = 5
MISSING_RSSI = -100
MAX_FLOORPLAN = 2 * 1024 * 1024
PNG_MAGIC, JPEG_MAGIC = b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"


class Fingerprints:
    def __init__(self) -> None:
        self.samples: dict[str, list[dict[str, float]]] = defaultdict(list)  # place → list of {scanner: rssi}
        self.centroids: dict[str, dict[str, float]] = {}

    def add(self, place: str, rssi: dict[str, float]) -> None:
        if rssi:
            self.samples[place].append(dict(rssi))
            self.samples[place] = self.samples[place][-500:]

    def fit(self) -> dict[str, int]:
        self.centroids = {}
        for place, rows in self.samples.items():
            if len(rows) < MIN_SAMPLES:
                continue
            scanners = {s for r in rows for s in r}
            self.centroids[place] = {s: statistics.median(r.get(s, MISSING_RSSI) for r in rows) for s in scanners}
        return {p: len(self.samples[p]) for p in self.centroids}

    def locate(self, rssi: dict[str, float], max_distance: float = 25.0) -> dict:
        if not self.centroids or not rssi:
            return {"place": "unknown", "distance": None}
        best, best_d = None, math.inf
        for place, c in self.centroids.items():
            keys = set(c) | set(rssi)
            d = math.sqrt(sum((rssi.get(k, MISSING_RSSI) - c.get(k, MISSING_RSSI)) ** 2 for k in keys) / max(1, len(keys)))
            if d < best_d:
                best, best_d = place, d
        return {"place": best if best_d <= max_distance else "unknown", "distance": round(best_d, 1)}


def ap_place(attributes: dict, mapping: dict[str, str]) -> str | None:
    """Coarse place from the access point a phone is connected to (UniFi attributes ap_mac / essid)."""
    ap = (attributes or {}).get("ap_mac") or (attributes or {}).get("access_point")
    if not ap:
        return None
    return mapping.get(str(ap).lower())


def co2_trend(samples: list[tuple[datetime, float]], min_hours: float = 1.5) -> dict:
    """Least-squares slope in ppm per hour over the samples; hint if clearly falling or rising."""
    pts = [(t, v) for t, v in samples if v is not None]
    if len(pts) < 4:
        return {"slope": None, "hint": None}
    t0 = pts[0][0]
    xs = [(t - t0).total_seconds() / 3600 for t, _ in pts]
    if xs[-1] < min_hours:
        return {"slope": None, "hint": None}
    ys = [v for _, v in pts]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs) or 1
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / den
    hint = "falling" if slope <= -30 else "rising" if slope >= 30 else "flat"
    return {"slope": round(slope), "hint": hint}


def validate_floorplan(b64: str) -> tuple[bytes, str]:
    """Decode an uploaded floor plan. Only PNG/JPEG, at most 2 MB. Raises ValueError."""
    if not isinstance(b64, str) or len(b64) > MAX_FLOORPLAN * 4 // 3 + 16:
        raise ValueError("floor plan too large (max 2 MB)")
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception as err:  # noqa: BLE001
        raise ValueError("invalid encoding") from err
    if len(data) > MAX_FLOORPLAN:
        raise ValueError("floor plan too large (max 2 MB)")
    if data.startswith(PNG_MAGIC):
        return data, "image/png"
    if data.startswith(JPEG_MAGIC):
        return data, "image/jpeg"
    raise ValueError("only PNG or JPEG")
