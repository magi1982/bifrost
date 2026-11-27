"""Bluetooth nearby (0.11c) – what the Shellys hear, where it is, calibration, zones.

Input: Home Assistant's advertisement stream (WebSocket ``bluetooth/subscribe_advertisements``): per advertisement
the address, the scanner (``source``), signal strength, name, manufacturer data and service UUIDs.

* **Type** from public identifiers only (Apple message type, company id, service UUID, advertised name) – as short
  as possible ("iPhone", "AirPods", "Android", "Samsung TV"); a guess is marked with ``guess=True`` (UI: ≈).
* **Rotating addresses** (resolvable private: top bits 01) are never stored – only kept in memory for 15 minutes.
  A phone with its IRK in HA's *Private BLE Device* is known by name through its tracker's ``current_address``.
* **Fixed addresses** are remembered (store) and forgotten after 90 days unless hidden or placed.
* **Position**: with calibration samples a k-nearest-neighbour match over all scanners (fingerprints, works in
  timber houses where ceilings damp little); without, a weighted centre of the strongest placed scanners.
* **Calibration**: the owner stands on a point and taps *Measure*; 20 s of signal strength per scanner become one
  sample; leave-one-out gives the expected accuracy per floor.
"""

from __future__ import annotations

import math
import re
import statistics
import threading
import time
from datetime import UTC, datetime, timedelta

ADDR = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
PRESENT_S = 120  # seen within the last 2 minutes = present
ROTATING_KEEP = timedelta(minutes=15)
FIXED_KEEP = timedelta(days=90)
MIN_RSSI = -100.0
CAL_SECONDS = 20
MAX_DEVICES = 1500
MAX_SAMPLES = 400

APPLE = 0x004C
COMPANIES = {
    0x0006: ("Windows PC", "pc"),
    0x0075: ("Samsung", "samsung"),
    0x0087: ("Garmin", "watch"),
    0x00E0: ("Google", "android"),
    0x0157: ("Xiaomi", "band"),
    0x038F: ("Xiaomi", "sensor"),
    0x02E5: ("Espressif", "sensor"),
    0x0499: ("Ruuvi", "sensor"),
    0x0059: ("Nordic", "tag"),
    0x00D2: ("Bose", "audio"),
    0x012D: ("Sony", "audio"),
    0x0310: ("JBL", "audio"),
    0x0822: ("Tesla", "car"),
}
SERVICES = {
    "fe2c": ("Android", "android"),
    "fcd2": ("BTHome", "sensor"),
    "fe95": ("Xiaomi", "sensor"),
    "feed": ("Tile", "tag"),
    "feaa": ("Beacon", "tag"),
    "fd6f": ("Phone", "phone"),
    "181a": ("Sensor", "sensor"),
    "fef3": ("Android", "android"),
}
APPLE_TYPES = {
    0x10: ("iPhone", "phone", True),
    0x0C: ("iPhone", "phone", True),
    0x07: ("AirPods", "audio", False),
    0x12: ("Find My", "tag", True),
    0x09: ("Apple TV", "tv", True),
    0x0F: ("iPhone", "phone", True),
    0x05: ("AirDrop", "phone", True),
    0x16: ("Apple", "phone", True),
}


def is_rotating(address: str) -> bool:
    """Resolvable private address (top two bits 01) – changes every ~15 minutes."""
    try:
        return int(address[:2], 16) >> 6 == 0b01
    except ValueError:
        return False


def _uuid16(u: str) -> str:
    u = str(u).lower()
    return u[4:8] if len(u) == 36 and u.endswith("-0000-1000-8000-00805f9b34fb") else u


def classify(adv: dict) -> tuple[str, str, bool]:
    """(short label, kind, guess) from public identifiers. kind: phone/watch/audio/tv/tag/sensor/pc/car/android/…"""
    name = str(adv.get("name") or "").strip()
    md = adv.get("manufacturer_data") or {}
    ids = {}
    for k, v in md.items():
        try:
            ids[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    if APPLE in ids:
        try:
            first = int(ids[APPLE][:2], 16)
        except ValueError:
            first = -1
        label, kind, guess = APPLE_TYPES.get(first, ("Apple", "phone", True))
        if re.search(r"watch", name, re.I):
            return "Watch", "watch", False
        return label, kind, guess
    for u in adv.get("service_uuids") or []:
        hit = SERVICES.get(_uuid16(u))
        if hit:
            return (name[:24] or hit[0]), hit[1], not name
    for cid, (label, kind) in COMPANIES.items():
        if cid in ids:
            if name:
                if re.search(r"\btv\b|\[tv\]", name, re.I):
                    return f"{label} TV", "tv", False
                if re.search(r"watch|band|fit", name, re.I):
                    kind = "watch"
                rest = re.sub(re.escape(label), "", _short(name), flags=re.I).strip(" -")
                return (f"{label} {rest}".strip())[:28], kind, False
            return label, kind, True
    if name:
        kind = (
            "tv"
            if re.search(r"\btv\b|\[tv\]", name, re.I)
            else "audio"
            if re.search(r"buds|pods|headphone|speaker|jbl|bose|sony", name, re.I)
            else "watch"
            if re.search(r"watch|band", name, re.I)
            else "device"
        )
        return _short(name), kind, False
    return "Bluetooth", "device", True


def _short(name: str) -> str:
    n = re.sub(r"[\[\]]", "", name).strip()
    n = re.sub(r"(?i)^samsung\s+", "", n)
    return n[:22]


class Device:
    __slots__ = ("address", "label", "kind", "guess", "name", "rotating", "first", "last", "rssi", "seen", "hidden", "irk")

    def __init__(self, address: str, now: float) -> None:
        self.address, self.first, self.last = address, now, now
        self.label, self.kind, self.guess, self.name = "Bluetooth", "device", True, ""
        self.rotating = is_rotating(address)
        self.rssi: dict[str, float] = {}  # source → smoothed rssi
        self.seen: dict[str, float] = {}  # source → last time
        self.hidden = False
        self.irk: str | None = None  # tracker entity id when resolved by Private BLE Device


class Tracker:
    """In-memory view of all advertising devices; fixed addresses are persisted by the caller."""

    def __init__(self) -> None:
        self.devices: dict[str, Device] = {}
        self.sources: dict[str, dict] = {}  # scanner source → {"name", "last", "count"}
        self._lock = threading.Lock()
        self.listeners: list = []  # callables(address, source, rssi, t) – calibration

    def ingest(self, adverts: list[dict], now: float | None = None) -> int:
        now = time.time() if now is None else now
        n = 0
        with self._lock:
            for a in adverts or []:
                addr = str(a.get("address") or "").upper()
                src = str(a.get("source") or "").upper()
                if not ADDR.match(addr) or not src:
                    continue
                try:
                    rssi = max(MIN_RSSI, min(0.0, float(a.get("rssi"))))
                except (TypeError, ValueError):
                    continue
                d = self.devices.get(addr)
                if d is None:
                    if len(self.devices) >= MAX_DEVICES:
                        continue
                    d = self.devices[addr] = Device(addr, now)
                d.last = now
                label, kind, guess = classify(a)
                if not (d.name and label == "Bluetooth"):
                    d.label, d.kind, d.guess = label, kind, guess
                if a.get("name"):
                    d.name = str(a["name"])[:40]
                prev = d.rssi.get(src)
                d.rssi[src] = rssi if prev is None or now - d.seen.get(src, 0) > 30 else 0.7 * prev + 0.3 * rssi
                d.seen[src] = now
                s = self.sources.setdefault(src, {"name": src, "last": now, "count": 0})
                s["last"], s["count"] = now, s["count"] + 1
                n += 1
                for fn in list(self.listeners):
                    fn(addr, src, rssi, now)
        return n

    def set_source_names(self, names: dict[str, str]) -> None:
        with self._lock:
            for src, name in names.items():
                self.sources.setdefault(src.upper(), {"name": name, "last": 0, "count": 0})["name"] = name

    def prune(self, now: float | None = None, keep: set[str] | None = None) -> list[str]:
        """Drop rotating devices after 15 min and fixed ones after 90 days (unless kept). Returns dropped fixed addresses."""
        now = time.time() if now is None else now
        dropped = []
        with self._lock:
            for addr, d in list(self.devices.items()):
                age = now - d.last
                if (d.rotating and age > ROTATING_KEEP.total_seconds()) or (not d.rotating and age > FIXED_KEEP.total_seconds() and addr not in (keep or set())):
                    del self.devices[addr]
                    if not d.rotating:
                        dropped.append(addr)
        return dropped

    def present(self, now: float | None = None) -> list[Device]:
        now = time.time() if now is None else now
        with self._lock:
            return [d for d in self.devices.values() if now - d.last <= PRESENT_S]

    def vector(self, d: Device, now: float | None = None) -> dict[str, float]:
        """Current signal strength per scanner (only scanners that heard it in the last minute)."""
        now = time.time() if now is None else now
        return {s: r for s, r in d.rssi.items() if now - d.seen.get(s, 0) <= 60}


# --- positions -------------------------------------------------------------------------------
def _w(rssi: float) -> float:
    return 10 ** ((rssi + 100) / 20)


def centroid(vec: dict[str, float], scanners: dict[str, dict]) -> dict | None:
    """Weighted centre of the strongest placed scanners on the floor of the strongest one."""
    placed = sorted(((r, scanners[s]) for s, r in vec.items() if s in scanners), key=lambda x: -x[0])
    if not placed:
        return None
    floor = placed[0][1]["floor"]
    top = [p for p in placed if p[1]["floor"] == floor][:3]
    tw = sum(_w(r) for r, _ in top)
    x = sum(_w(r) * s["x"] for r, s in top) / tw
    y = sum(_w(r) * s["y"] for r, s in top) / tw
    err = 4.0 if len(top) == 1 else 3.0 if len(top) == 2 else 2.5
    return {"floor": floor, "x": round(x, 1), "y": round(y, 1), "err": err, "method": "centre"}


def _dist(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1e9
    return math.sqrt(sum((a.get(k, MIN_RSSI) - b.get(k, MIN_RSSI)) ** 2 for k in keys) / len(keys))


def knn(vec: dict[str, float], samples: list[dict], k: int = 3) -> dict | None:
    """Fingerprint match over all scanners of the house: floor by majority of the k nearest, position = their mean."""
    if len(samples) < 3 or not vec:
        return None
    near = sorted(samples, key=lambda s: _dist(vec, s["vec"]))[:k]
    floors = [s["floor"] for s in near]
    floor = max(set(floors), key=floors.count)
    same = [s for s in near if s["floor"] == floor]
    x = statistics.fmean(s["x"] for s in same)
    y = statistics.fmean(s["y"] for s in same)
    spread = max(math.hypot(s["x"] - x, s["y"] - y) for s in same)
    return {"floor": floor, "x": round(x, 1), "y": round(y, 1), "err": round(max(1.0, spread), 1), "method": "fingerprint", "floor_sure": floors.count(floor) == len(floors)}


def locate(vec: dict[str, float], scanners: dict[str, dict], samples: list[dict]) -> dict | None:
    return knn(vec, samples) or centroid(vec, scanners)


def accuracy(samples: list[dict]) -> dict[str, dict]:
    """Leave-one-out error per floor: how far the fingerprint match lands from where the owner stood."""
    out: dict[str, list[float]] = {}
    floor_ok: dict[str, list[bool]] = {}
    for i, s in enumerate(samples):
        rest = samples[:i] + samples[i + 1 :]
        p = knn(s["vec"], rest)
        if not p:
            continue
        floor_ok.setdefault(s["floor"], []).append(p["floor"] == s["floor"])
        if p["floor"] == s["floor"]:
            out.setdefault(s["floor"], []).append(math.hypot(p["x"] - s["x"], p["y"] - s["y"]))
    res = {}
    for f, oks in floor_ok.items():
        errs = out.get(f, [])
        res[f] = {"error_m": round(statistics.median(errs), 1) if errs else None, "floor_hit": round(100 * sum(oks) / len(oks)), "samples": len(oks)}
    return res


def proposals(m: dict, per_m2: float = 9.0) -> list[dict]:
    """Calibration points: about one per 9 m² of each room/outside area (at least one), at rectangle centres."""
    pts = []
    for r in m.get("rooms", []):
        for q in r["rects"]:
            area = q[2] * q[3]
            n = max(1, round(area / per_m2)) if q is r["rects"][0] or area >= 4 else 0
            cols = max(1, round(math.sqrt(n * q[2] / max(q[3], 0.1))))
            rows = max(1, math.ceil(n / cols))
            for i in range(rows):
                for j in range(cols):
                    pts.append({"x": round(q[0] + (j + 0.5) * q[2] / cols, 1), "y": round(q[1] + (i + 0.5) * q[3] / rows, 1), "area": r["area"], "outside": bool(r.get("outside"))})
    return pts[:120]


def in_rects(rects: list, x: float, y: float) -> bool:
    return any(q[0] <= x <= q[0] + q[2] and q[1] <= y <= q[1] + q[3] for q in rects)


class Hysteresis:
    """Zone occupancy: on after `enter` seconds inside, off after `leave` seconds outside."""

    def __init__(self, enter: float = 20, leave: float = 60) -> None:
        self.enter, self.leave = enter, leave
        self.state: dict[str, bool] = {}
        self._since: dict[str, float] = {}

    def update(self, key: str, inside: bool, now: float) -> bool:
        cur = self.state.get(key, False)
        if inside == cur:
            self._since.pop(key, None)
            return cur
        start = self._since.setdefault(key, now)
        if now - start >= (self.enter if inside else self.leave):
            self.state[key] = inside
            self._since.pop(key, None)
        return self.state.get(key, False)


class Calibration:
    """One measurement at a time: collect 20 s of rssi per scanner for the chosen device."""

    def __init__(self, tracker: Tracker) -> None:
        self.tracker = tracker
        self.device: str | None = None  # address or tracker entity id (resolved each time)
        self.active: dict | None = None
        self._buf: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        tracker.listeners.append(self._on)

    def _on(self, addr: str, src: str, rssi: float, t: float) -> None:
        a = self.active
        if a and addr == a["address"] and t <= a["until"]:
            with self._lock:
                self._buf.setdefault(src, []).append(rssi)

    def start(self, address: str, floor: str, x: float, y: float, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            self._buf = {}
            self.active = {"address": address, "floor": floor, "x": x, "y": y, "until": now + CAL_SECONDS, "started": now}
        return self.status(now)

    def status(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        a = self.active
        if not a:
            return {"running": False}
        with self._lock:
            live = {s: round(statistics.median(v), 1) for s, v in self._buf.items() if v}
        return {"running": now < a["until"], "left": max(0, round(a["until"] - now)), "floor": a["floor"], "x": a["x"], "y": a["y"], "live": live}

    def finish(self, now: float | None = None) -> dict | None:
        """The finished sample (or None): median per scanner, quality by number of scanners and spread."""
        now = time.time() if now is None else now
        a = self.active
        if not a or now < a["until"]:
            return None
        with self._lock:
            buf, self._buf, self.active = self._buf, {}, None
        vec = {s: round(statistics.median(v), 1) for s, v in buf.items() if len(v) >= 2}
        spread = statistics.fmean(statistics.pstdev(v) for v in buf.values() if len(v) >= 2) if vec else 99
        quality = "good" if len(vec) >= 3 and spread < 6 else "weak" if vec else "none"
        return {"floor": a["floor"], "x": a["x"], "y": a["y"], "vec": vec, "quality": quality, "scanners": len(vec), "at": datetime.now(UTC).isoformat(timespec="seconds")}
