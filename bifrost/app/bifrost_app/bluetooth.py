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
WINDOW_S = 10.0  # median window per scanner
HOLD_S = 8.0  # a scanner keeps its value this long after the last advert …
FADE_S = 30.0  # … then fades to MIN_RSSI over this time
CAL_SECONDS = 20
MAX_DEVICES = 1500
TRANSIENT = timedelta(hours=1)  # a "fixed" address seen for less than this and gone for this long was just passing by
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
    """A private address that changes: resolvable (top two bits 01) or non-resolvable (00) – both change every few
    minutes. Random static (11) and public addresses stay fixed (Find My tags are caught by their content, see ingest)."""
    try:
        return int(address[:2], 16) >> 6 in (0b00, 0b01)
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
    __slots__ = ("address", "label", "kind", "guess", "name", "rotating", "first", "last", "rssi", "seen", "hidden", "irk", "win")

    def __init__(self, address: str, now: float) -> None:
        self.address, self.first, self.last = address, now, now
        self.label, self.kind, self.guess, self.name = "Bluetooth", "device", True, ""
        self.rotating = is_rotating(address)
        self.rssi: dict[str, float] = {}  # source → smoothed rssi
        self.seen: dict[str, float] = {}  # source → last time
        self.win: dict[str, list[tuple[float, float]]] = {}  # source → raw readings of the last WINDOW_S seconds
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
                s = self.sources.setdefault(src, {"name": src, "last": now, "count": 0})
                s["last"], s["count"] = now, s["count"] + 1  # the gateway is alive, whatever it heard
                d = self.devices.get(addr)
                if d is None:
                    if len(self.devices) >= MAX_DEVICES:
                        self._evict()
                    d = self.devices[addr] = Device(addr, now)
                d.last = now
                label, kind, guess = classify(a)
                if not (d.name and label == "Bluetooth"):
                    d.label, d.kind, d.guess = label, kind, guess
                if label == "Find My":
                    d.rotating = True  # Find My tags change their (random static) address every ~15 min
                if a.get("name"):
                    d.name = str(a["name"])[:40]
                d.rssi[src] = _filtered(d, src, rssi, now)
                d.seen[src] = now
                n += 1
                for fn in list(self.listeners):
                    fn(addr, src, rssi, now)
        return n

    def _evict(self) -> None:
        """Full: forget the device heard longest ago – changing addresses first, then fixed ones. (Lock held.)"""
        victim = min(self.devices.values(), key=lambda d: (not d.rotating, d.last))
        del self.devices[victim.address]

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
                passing = not d.rotating and d.last - d.first < TRANSIENT.total_seconds() and age > TRANSIENT.total_seconds()
                old = not d.rotating and age > FIXED_KEEP.total_seconds()
                if (d.rotating and age > ROTATING_KEEP.total_seconds()) or ((passing or old) and addr not in (keep or set())):
                    del self.devices[addr]
                    if not d.rotating:
                        dropped.append(addr)
        return dropped

    def present(self, now: float | None = None) -> list[Device]:
        now = time.time() if now is None else now
        with self._lock:
            return [d for d in self.devices.values() if now - d.last <= PRESENT_S]

    def vector(self, d: Device, now: float | None = None) -> dict[str, float]:
        """Current signal strength per scanner. A scanner that stops hearing the device fades towards −100 dBm
        over FADE_S seconds instead of dropping out at once (a missed advert must not move the dot)."""
        now = time.time() if now is None else now
        out = {}
        for s, r in d.rssi.items():
            age = now - d.seen.get(s, 0)
            if age <= HOLD_S:
                out[s] = r
            elif age <= HOLD_S + FADE_S:
                out[s] = r + (MIN_RSSI - r) * (age - HOLD_S) / FADE_S
        return out


def _filtered(d: Device, src: str, rssi: float, now: float) -> float:
    """Median of the last WINDOW_S seconds (single outliers – a body between phone and Shelly – do not count),
    then a light exponential filter. After a long silence the filter starts fresh."""
    win = [(t, v) for t, v in d.win.get(src, []) if now - t <= WINDOW_S]
    win.append((now, rssi))
    d.win[src] = win[-20:]
    med = statistics.median(v for _, v in d.win[src])
    prev = d.rssi.get(src)
    if prev is None or now - d.seen.get(src, 0) > HOLD_S + FADE_S:
        return med
    return prev + 0.4 * (med - prev)


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


def knn(vec: dict[str, float], samples: list[dict], k: int | None = None) -> dict | None:
    """Fingerprint match over all scanners of the house: floor by weighted majority of the k nearest calibration
    points, position = their mean weighted by closeness (lands between points instead of snapping to one)."""
    if len(samples) < 3 or not vec:
        return None
    k = k or max(3, min(5, len(samples) // 4))
    near = sorted(((_dist(vec, s["vec"]), s) for s in samples), key=lambda x: x[0])[:k]
    wts = [(1.0 / (d + 1.0) ** 2, s) for d, s in near]
    score: dict[str, float] = {}
    for w, s in wts:
        score[s["floor"]] = score.get(s["floor"], 0.0) + w
    floor = max(score, key=score.get)
    same = [(w, s) for w, s in wts if s["floor"] == floor]
    tw = sum(w for w, _ in same)
    x = sum(w * s["x"] for w, s in same) / tw
    y = sum(w * s["y"] for w, s in same) / tw
    spread = math.sqrt(sum(w * ((s["x"] - x) ** 2 + (s["y"] - y) ** 2) for w, s in same) / tw)
    return {
        "floor": floor,
        "x": round(x, 2),
        "y": round(y, 2),
        "err": round(max(1.0, 1.5 * spread), 1),
        "method": "fingerprint",
        "floor_sure": score[floor] >= 0.75 * sum(score.values()),
    }


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


# --- calm positions ----------------------------------------------------------------------------
CALM = {
    # alpha: low-pass of the measured position per step · dead: dead band in m · speed: max m/s · hold/agree: floor change
    "calm": {"alpha": 0.25, "dead": 0.8, "speed": 1.0, "hold": 20.0, "agree": 3},
    "normal": {"alpha": 0.4, "dead": 0.5, "speed": 1.5, "hold": 15.0, "agree": 2},
    "fast": {"alpha": 0.7, "dead": 0.3, "speed": 3.0, "hold": 6.0, "agree": 1},
}


class Smoother:
    """Keeps the shown position of each device calm: walking-speed limit, dead band, and a floor change only
    after agreeing results (or when the old floor's scanners no longer hear the device)."""

    FORGET_S = 300.0

    def __init__(self) -> None:
        self.state: dict[str, dict] = {}
        self._lock = threading.Lock()

    def update(self, key: str, raw: dict | None, now: float, mode: str = "normal", old_floor_heard: bool = True) -> dict | None:
        p = CALM.get(mode, CALM["normal"])
        with self._lock:
            for k in [k for k, v in self.state.items() if now - v["t"] > self.FORGET_S]:
                del self.state[k]
            if raw is None:
                return None
            st = self.state.get(key)
            if st is None:
                st = self.state[key] = {"floor": raw["floor"], "x": raw["x"], "y": raw["y"], "fx": raw["x"], "fy": raw["y"], "t": now, "cand": None, "since": now, "n": 0, "err": raw.get("err", 2.0)}
                return self._out(st, raw)
            dt = max(0.0, min(30.0, now - st["t"]))
            st["t"] = now
            if raw["floor"] != st["floor"]:
                if st["cand"] != raw["floor"]:
                    st["cand"], st["since"], st["n"] = raw["floor"], now, 0
                st["n"] += 1
                if not old_floor_heard or st["n"] >= p["agree"] or now - st["since"] >= p["hold"]:
                    st.update(floor=raw["floor"], x=raw["x"], y=raw["y"], fx=raw["x"], fy=raw["y"], cand=None, n=0, err=raw.get("err", 2.0))
                return self._out(st, raw)
            st["cand"], st["n"] = None, 0
            st["err"] = 0.7 * st["err"] + 0.3 * raw.get("err", st["err"])
            # 1. low-pass of the measured position (noise), 2. the shown dot follows it outside the dead band at walking speed
            st["fx"] += p["alpha"] * (raw["x"] - st["fx"])
            st["fy"] += p["alpha"] * (raw["y"] - st["fy"])
            dx, dy = st["fx"] - st["x"], st["fy"] - st["y"]
            dist = math.hypot(dx, dy)
            # the dead band only decides when the dot starts moving; once it moves it goes all the way (no lag)
            if dist <= (0.1 if st.get("moving") else max(p["dead"], st["err"] / 2)):
                st["moving"] = False
                return self._out(st, raw)
            st["moving"] = True
            step = min(dist, p["speed"] * max(dt, 1.0))
            st["x"] += dx / dist * step
            st["y"] += dy / dist * step
            return self._out(st, raw)

    @staticmethod
    def _out(st: dict, raw: dict) -> dict:
        return {**raw, "floor": st["floor"], "x": round(st["x"], 2), "y": round(st["y"], 2), "err": round(st["err"], 1), "raw": {"x": raw["x"], "y": raw["y"], "floor": raw["floor"]}}
