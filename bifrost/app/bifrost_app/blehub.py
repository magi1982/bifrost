"""Bluetooth hub (0.11c): ties the tracker to the house map, people, calibration and the published entities."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import UTC, datetime

from . import bluetooth as bt
from .housemap import room_at

LOG = logging.getLogger(__name__)
MAX_MOVES = 10
HOUSE_KINDS = ("tv", "sensor", "pc", "audio", "device")


def _slug(name: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "x")[:40]


def _mac_int(mac: str) -> int | None:
    try:
        return int(mac.replace(":", "").replace("-", ""), 16)
    except ValueError:
        return None


def mac_match(source: str, macs: list[str]) -> bool:
    """A scanner's Bluetooth address is usually its Wi-Fi MAC or a few above (Shelly: +2)."""
    s = _mac_int(source)
    if s is None:
        return False
    for m in macs:
        v = _mac_int(m)
        if v is not None and 0 <= s - v <= 3:
            return True
    return False


class BleHub:
    def __init__(self, store) -> None:  # noqa: ANN001
        self.store = store
        self.tracker = bt.Tracker()
        self.cal = bt.Calibration(self.tracker)
        self.zones = bt.Hysteresis(20, 60)
        self.status = {"connected": False, "supported": None, "error": None, "since": None}
        self._lock = threading.Lock()
        self.hidden: set[str] = set(self._load("ble_hidden", []))
        self.settings = {"on": True, "hide_house": False, **self._load("ble_settings", {})}
        self.samples: list[dict] = self._load("calib_samples", [])
        self.cal_device: str | None = self.store.get_value("calib_device")
        self.moves: dict[str, list[dict]] = self._load("ble_moves", {})
        self._where: dict[str, str] = {}
        self._restore_fixed()
        self._saved = 0.0

    # --- storage ---------------------------------------------------------------------
    def _load(self, key: str, default):  # noqa: ANN001, ANN202
        try:
            v = json.loads(self.store.get_value(key) or "null")
        except ValueError:
            v = None
        return default if v is None else v

    def _save(self, key: str, value) -> None:  # noqa: ANN001
        self.store.set_value(key, json.dumps(value))

    def _restore_fixed(self) -> None:
        for addr, r in (self._load("ble_fixed", {}) or {}).items():
            if not bt.ADDR.match(addr):
                continue
            d = bt.Device(addr, float(r.get("last", 0)))
            d.first = float(r.get("first", d.last))
            d.label, d.kind, d.guess, d.name = r.get("label", "Bluetooth"), r.get("kind", "device"), bool(r.get("guess", True)), r.get("name", "")
            self.tracker.devices[addr] = d

    def persist(self, now: float | None = None, keep: set[str] | None = None) -> None:
        now = time.time() if now is None else now
        if now - self._saved < 300:
            return
        self._saved = now
        self.tracker.prune(now, keep=(keep or set()) | self.hidden)
        fixed = {
            d.address: {"label": d.label, "kind": d.kind, "guess": d.guess, "name": d.name, "first": round(d.first), "last": round(d.last)}
            for d in list(self.tracker.devices.values())
            if not d.rotating
        }
        self._save("ble_fixed", fixed)

    # --- settings ------------------------------------------------------------------------
    def set_settings(self, body: dict) -> dict:
        if "on" in body:
            if not isinstance(body["on"], bool):
                raise ValueError("on: true/false")
            self.settings["on"] = body["on"]
        if "hide_house" in body:
            if not isinstance(body["hide_house"], bool):
                raise ValueError("hide_house: true/false")
            self.settings["hide_house"] = body["hide_house"]
        if "address" in body:
            addr = str(body.get("address") or "").upper()
            if not bt.ADDR.match(addr) or not isinstance(body.get("hidden"), bool):
                raise ValueError("expected {address, hidden}")
            (self.hidden.add if body["hidden"] else self.hidden.discard)(addr)
            self._save("ble_hidden", sorted(self.hidden))
        self._save("ble_settings", self.settings)
        return {"settings": self.settings, "hidden": len(self.hidden)}

    # --- mapping scanners and phones ------------------------------------------------------
    def scanner_positions(self, maps: dict[str, dict], candidates: list[dict]) -> dict[str, dict]:
        """source address → {floor, x, y, id} for every placed scanner."""
        out = {}
        sources = list(self.tracker.sources)
        for floor, m in maps.items():
            for dev in m.get("devices", []):
                if dev.get("kind") != "scanner":
                    continue
                pos = {"floor": floor, "x": dev["x"], "y": dev["y"], "id": dev["id"]}
                if dev["id"].startswith("ble:"):
                    out[dev["id"][4:]] = pos
                    continue
                cand = next((c for c in candidates if c["id"] == dev["id"]), None)
                for s in sources:
                    if cand and mac_match(s, cand.get("macs") or []):
                        out[s] = pos
        return out

    @staticmethod
    def irk_addresses(states: dict[str, dict]) -> dict[str, dict]:
        """Current address of each phone resolved by HA's Private BLE Device (tracker attribute current_address)."""
        out = {}
        for eid, st in states.items():
            if not eid.startswith("device_tracker."):
                continue
            a = st.get("attributes") or {}
            addr = str(a.get("current_address") or "").upper()
            if bt.ADDR.match(addr):
                out[addr] = {"entity_id": eid, "name": str(a.get("friendly_name") or eid)}
        return out

    # --- positions --------------------------------------------------------------------------
    def positions(self, maps: dict[str, dict], candidates: list[dict], states: dict[str, dict], person_of: dict[str, str], now: float | None = None) -> list[dict]:
        """Every present device with label, kind and – when gateways are placed – position, floor and room."""
        now = time.time() if now is None else now
        scanners = self.scanner_positions(maps, candidates)
        irk = self.irk_addresses(states)
        rows = []
        for d in self.tracker.present(now):
            vec = self.tracker.vector(d, now)
            best = max(vec.items(), key=lambda kv: kv[1]) if vec else (None, None)
            pos = bt.locate(vec, scanners, self.samples) if vec else None
            info = irk.get(d.address)
            person = person_of.get(info["entity_id"]) if info else None
            room = None
            if pos and pos["floor"] in maps:
                room = room_at(maps[pos["floor"]], pos["x"], pos["y"])
                if room is None:
                    for r in maps[pos["floor"]].get("rooms", []):
                        if r.get("outside") and bt.in_rects(r["rects"], pos["x"], pos["y"]):
                            room = r["area"]
                            break
            house = not d.rotating and d.kind in HOUSE_KINDS and now - d.first > 12 * 3600
            rows.append(
                {
                    "address": d.address,
                    "short": d.address[-5:],
                    "label": info["name"] if info else d.label,
                    "kind": "phone" if info else d.kind,
                    "guess": False if info else d.guess,
                    "fixed": not d.rotating,
                    "irk": bool(info),
                    "person": person,
                    "house": house,
                    "hidden": d.address in self.hidden or (house and self.settings.get("hide_house")),
                    "best": self.tracker.sources.get(best[0], {}).get("name", best[0]) if best[0] else None,
                    "rssi": round(best[1]) if best[1] is not None else None,
                    "scanners": len(vec),
                    "pos": pos,
                    "room": room,
                }
            )
        rows.sort(key=lambda r: (not r["irk"], r["hidden"], -(r["rssi"] or -100)))
        return rows

    # --- zones and person locations ------------------------------------------------------------
    def evaluate(self, rows: list[dict], maps: dict[str, dict], people: list, now: float | None = None) -> dict:
        """Zone occupancy (with hysteresis) and where each person with an IRK phone is."""
        now = time.time() if now is None else now
        bound = [r for r in rows if r["person"] and r["pos"]]
        zones = []
        for floor, m in maps.items():
            for z in m.get("zones", []):
                inside = [r for r in bound if r["pos"]["floor"] == floor and bt.in_rects(z["rects"], r["pos"]["x"], r["pos"]["y"])]
                key = f"{floor}|{z['name']}"
                on = self.zones.update(key, bool(inside), now)
                zones.append({"name": z["name"], "slug": _slug(z["name"]), "floor": floor, "on": on, "people": sorted({r["person"] for r in inside}) if on else []})
        locs = {}
        for p in people:
            mine = [r for r in rows if r["person"] == p.name and r["pos"]]
            where = (mine[0]["room"] or mine[0]["pos"]["floor"]) if mine else "unknown"
            locs[p.name] = {"slug": _slug(p.name), "where": where, "floor": mine[0]["pos"]["floor"] if mine else None}
            if mine and self._where.get(p.name) != where:
                self._where[p.name] = where
                mv = self.moves.setdefault(p.name, [])
                mv.insert(0, {"to": where, "at": datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds")})
                del mv[MAX_MOVES:]
                self._save("ble_moves", self.moves)
        return {"zones": zones, "people": locs}

    # --- calibration ------------------------------------------------------------------------------
    def cal_start(self, body: dict, maps: dict[str, dict], states: dict[str, dict]) -> dict:
        dev, floor = str(body.get("device") or ""), body.get("floor")
        if floor not in maps:
            raise ValueError("unknown floor")
        x, y = body.get("x"), body.get("y")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y)):
            raise ValueError("x and y must be numbers")
        m = maps[floor]
        if not (0 <= x <= m.get("w", 80) and 0 <= y <= m.get("h", 80)):
            raise ValueError("point outside the floor")
        addr = self.resolve(dev, states)
        if not addr:
            raise ValueError("device not heard right now")
        self.cal_device = dev
        self.store.set_value("calib_device", dev)
        return self.cal.start(addr, floor, round(float(x), 1), round(float(y), 1))

    def resolve(self, dev: str, states: dict[str, dict]) -> str | None:
        """A calibration device: an IRK tracker (its current address) or a fixed address."""
        if dev.startswith("device_tracker."):
            for addr, info in self.irk_addresses(states).items():
                if info["entity_id"] == dev:
                    return addr
            return None
        dev = dev.upper()
        return dev if bt.ADDR.match(dev) and dev in self.tracker.devices else None

    def cal_poll(self) -> dict:
        s = self.cal.status()
        done = self.cal.finish()
        if done:
            if done["vec"]:
                self.samples.append(done)
                del self.samples[: max(0, len(self.samples) - bt.MAX_SAMPLES)]
                self._save("calib_samples", self.samples)
            s = {"running": False, "last": done}
        names = {src: v.get("name", src) for src, v in self.tracker.sources.items()}
        if s.get("live"):
            s["live"] = {names.get(k, k): v for k, v in s["live"].items()}
        return s

    def cal_delete(self, index: object) -> dict:
        if index == "all":
            self.samples = []
        elif isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(self.samples):
            self.samples.pop(index)
        else:
            raise ValueError("index or 'all'")
        self._save("calib_samples", self.samples)
        return {"samples": len(self.samples)}

    def cal_view(self, maps: dict[str, dict], states: dict[str, dict]) -> dict:
        status = self.cal_poll()  # first: a finished measurement becomes a sample before the list is built
        irk = self.irk_addresses(states)
        devices = [{"id": i["entity_id"], "name": i["name"], "irk": True} for i in irk.values()]
        devices += [{"id": d.address, "name": f"{d.label} ({d.address[-5:]})", "irk": False} for d in self.tracker.present() if not d.rotating][:40]
        return {
            "devices": devices,
            "device": self.cal_device,
            "points": {f: bt.proposals(m) for f, m in maps.items()},
            "samples": [{"i": i, "floor": s["floor"], "x": s["x"], "y": s["y"], "quality": s["quality"], "scanners": s["scanners"]} for i, s in enumerate(self.samples)],
            "accuracy": bt.accuracy(self.samples),
            "status": status,
        }

    NO_BLE = re.compile(r"^(SH[A-Z0-9]{2,}-|SHSW|SHPLG|SHDM|SHIX|SHEM|SHHT|SHWT|SHDW|SHBTN|SHMOS|SHGS|SBBT|SBDW|SBHT|SBMO)|\b(gen ?1|shelly ?1(pm|l)?|shelly ?2\.5|dimmer ?2|plug ?s|h&t|blu)\b", re.I)

    def missing(self, candidates: list[dict]) -> list[dict]:
        """Devices that could be gateways but send nothing – with the likely reason."""
        out = []
        for c in candidates:
            if any(mac_match(s, c.get("macs") or []) for s in self.tracker.sources):
                continue
            text = f"{c.get('model') or ''} {c.get('name') or ''}"
            esphome = "esp" in (c.get("manufacturer") or "").lower() or "esphome" in text.lower()
            gen2 = re.search(r"\b(plus|pro|mini|gen ?[2-9]|S[0-9][A-Z]{2})", text, re.I)  # Plus/Pro/Mini/Gen2+ all have Bluetooth
            reason = "esphome" if esphome else "no_ble" if self.NO_BLE.search(text) and not gen2 else "enable"
            out.append({"name": c.get("name"), "model": c.get("model") or "", "area": c.get("area"), "reason": reason})
        return sorted(out, key=lambda x: (x["reason"] != "enable", x["name"] or ""))

    def view(self, rows: list[dict], scanners: dict[str, dict], now: float | None = None, candidates: list[dict] | None = None) -> dict:
        now = time.time() if now is None else now
        hide_house = bool(self.settings.get("hide_house"))
        rows = [{**r, "hidden": r["address"] in self.hidden or (r["house"] and hide_house)} for r in rows]  # switches apply at once
        srcs = [{"source": s, "name": v.get("name", s), "recent": now - v.get("last", 0) < 120, "placed": s in scanners} for s, v in sorted(self.tracker.sources.items())]
        return {
            "status": self.status,
            "settings": self.settings,
            "scanners": srcs,
            "devices": rows,
            "missing": self.missing(candidates or []),
            "counts": {
                "present": len(rows),
                "fixed": sum(1 for r in rows if r["fixed"]),
                "rotating": sum(1 for r in rows if not r["fixed"]),
                "irk": sum(1 for r in rows if r["irk"]),
                "hidden": sum(1 for r in rows if r["hidden"]),
            },
        }
