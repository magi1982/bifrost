"""People (0.4) – persons are defined in Bifrost only, not as HA persons or users.

Per person the owner links whatever exists: phone trackers, BLE identity (iPhone IRK), calendars,
an NFC user name from the alarm keypad, tags – or nothing (e.g. a child without phone).

The **ledger** answers, every minute, for each person: home / away / unclear – plus
"unknown people: at least N" for entries nothing explains. "Empty" is only allowed when
everybody is away and the unknown counter is 0.

Since 0.7 Bluetooth keys (iPhone IRK) live in Home Assistant ("Private BLE Device"), not in Bifrost.
Older installs may still hold keys: they are only listed masked and can be deleted, never read back.

**Visibility** – how well Bifrost can see a person – follows from the assigned sources alone, using
the Home Assistant standard ``source_type`` of a tracker instead of a list of integration names.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field

KIND = "person"
KINDS = ("household", "visitor")
ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")
NFC_RE = re.compile(r"^[\w .\-]{1,40}$", re.UNICODE)
MAX_LINKS = 10

HOME, AWAY, UNCLEAR = "home", "away", "unclear"
STRONG, MEDIUM, WEAK = "strong", "medium", "weak"

# Strength of an identity signal. The HA standard attribute ``source_type`` decides; the integration is only a fallback.
STRENGTH_BY_SOURCE_TYPE = {"gps": MEDIUM, "router": WEAK, "bluetooth_le": WEAK, "bluetooth": WEAK}
STRENGTH_BY_INTEGRATION = {"mobile_app": MEDIUM, "private_ble_device": WEAK, "unifi": WEAK, "bluetooth_le_tracker": WEAK, "ping": WEAK, "bermuda": MEDIUM}
GOOD, MEDIUM_VIS, INVISIBLE = "good", "medium", "invisible"
ROOM_WORDS = ("area", "bereich", "room", "raum")


def is_room_source(entity_id: str, meta: dict | None) -> bool:
    """A sensor that reports the room of a device (e.g. Bermuda's "Area" sensor)."""
    m = meta or {}
    if (m.get("integration") or "").lower() == "bermuda" and entity_id.startswith("sensor."):
        return True
    text = (entity_id + " " + (m.get("name") or "")).lower()
    return entity_id.startswith("sensor.") and any(w in text for w in ROOM_WORDS) and not m.get("unit")


def source_kind(entity_id: str, meta: dict | None) -> str:
    """gps / router / bluetooth / room / tag / other – what kind of source this is, for the UI and visibility."""
    m = meta or {}
    st = (m.get("source_type") or "").lower()
    if is_room_source(entity_id, m):
        return "room"
    if st == "gps" or (not st and (m.get("integration") or "") == "mobile_app"):
        return "gps"
    if st == "router":
        return "router"
    if st.startswith("bluetooth") or (m.get("integration") or "") in ("private_ble_device", "bluetooth_le_tracker", "ibeacon"):
        return "bluetooth"
    if entity_id.startswith("person."):
        return "person"
    return "other"


def source_strength(entity_id: str, meta: dict | None) -> str:
    m = meta or {}
    if is_room_source(entity_id, m):
        return MEDIUM  # a room is seen close by – better than "somewhere in Wi-Fi"
    st = (m.get("source_type") or "").lower()
    if st in STRENGTH_BY_SOURCE_TYPE:
        return STRENGTH_BY_SOURCE_TYPE[st]
    if entity_id.startswith("person."):
        return MEDIUM
    return STRENGTH_BY_INTEGRATION.get((m.get("integration") or "").lower(), WEAK)


def visibility(p: Person, meta: dict[str, dict] | None = None, wrong: dict[str, int] | None = None) -> dict:
    """good / medium / invisible – derived from the assigned sources, no setting needed."""
    meta, wrong = meta or {}, wrong or {}
    kinds = [{"entity_id": e, "kind": source_kind(e, meta.get(e)), "strength": WEAK if wrong.get(e, 0) >= 3 else source_strength(e, meta.get(e))} for e in p.sources]
    strong_access = bool(p.access_users)
    if any(k["strength"] in (MEDIUM, STRONG) for k in kinds) or (kinds and strong_access):
        level = GOOD
    elif kinds or strong_access:
        level = MEDIUM_VIS
    else:
        level = INVISIBLE
    return {"level": level, "sources": kinds, "access": list(p.access_users), "calendars": list(p.calendars)}


@dataclass
class Person:
    id: str
    name: str
    kind: str = "household"
    may_be_alone: bool = True
    trackers: list[str] = field(default_factory=list)
    calendars: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    nfc_user: str = ""  # legacy (≤ 0.4.2): single access user, migrated into access_users
    irk: str = ""  # legacy (≤ 0.4.2): migrated into IRK objects (Setup)
    access_users: list[str] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return self.trackers + self.tags


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return (s or "person")[:40]


def _entities(value, prefix: tuple[str, ...], label: str) -> list[str]:  # noqa: ANN001
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_LINKS:
        raise ValueError(f"{label}: list of at most {MAX_LINKS} entities expected")
    out = []
    for v in value:
        if not isinstance(v, str) or not ENTITY_RE.match(v) or not v.startswith(prefix):
            raise ValueError(f"{label}: invalid entity id")
        if v not in out:
            out.append(v)
    return out


def validate(body: dict, existing: Person | None = None) -> Person:
    """Validate a person from the API. Raises ValueError with a safe message."""
    if not isinstance(body, dict):
        raise ValueError("invalid body")
    name = body.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or any(c in name for c in "<>{}"):
        raise ValueError("name: 1–40 characters")
    name = name.strip()
    pid = body.get("id") or (existing.id if existing else slugify(name))
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise ValueError("invalid id")
    kind = body.get("kind", "household")
    if kind not in KINDS:
        raise ValueError("invalid kind")
    nfc = body.get("nfc_user") or ""
    if nfc and (not isinstance(nfc, str) or not NFC_RE.match(nfc)):
        raise ValueError("nfc_user: letters, digits, space, . _ - (max 40)")
    return Person(
        id=pid,
        name=name,
        kind=kind,
        may_be_alone=bool(body.get("may_be_alone", True)),
        trackers=_entities(body.get("trackers"), ("device_tracker.", "person.", "binary_sensor.", "sensor."), "trackers"),
        calendars=_entities(body.get("calendars"), ("calendar.",), "calendars"),
        tags=_entities(body.get("tags"), ("device_tracker.", "binary_sensor.", "sensor."), "tags"),
        nfc_user=nfc.strip(),
        irk="",  # 0.7: keys live in Home Assistant (Private BLE Device), never in Bifrost
    )


def from_dict(d: dict) -> Person:
    p = Person(**{k: d[k] for k in Person.__dataclass_fields__ if k in d})
    if p.nfc_user and p.nfc_user not in p.access_users:
        p.access_users = [*p.access_users, p.nfc_user]
    return p


def public(p: Person) -> dict:
    """API representation – never contains an IRK."""
    d = asdict(p)
    d.pop("irk", None)
    d.pop("nfc_user", None)
    return d


def mask(key: str) -> str:
    return ("••••" + key[-4:]) if key else ""


DENIED_RE = re.compile(r"denied|verweigert|abgelehnt|invalid|ungültig|falsch|wrong|unknown.?(code|tag|user)|unbekannt|rejected|failed|fehlgeschlagen", re.I)


class PeopleStore:
    def __init__(self, store) -> None:  # noqa: ANN001
        self.store = store

    def all(self) -> list[Person]:
        return [from_dict(d) for d in self.store.list_objs(KIND)]

    def get(self, pid: str) -> Person | None:
        d = self.store.get_obj(KIND, pid)
        return from_dict(d) if d else None

    def save(self, body: dict) -> Person:
        """Name, kind and "may be alone" come from the People tab; sources are assigned in Setup and kept."""
        existing = self.get(body.get("id")) if isinstance(body.get("id"), str) else None
        p = validate(body, existing)
        if existing is None and self.get(p.id) is not None:
            raise ValueError("a person with this id exists")
        if existing is None and len(self.all()) >= 30:
            raise ValueError("at most 30 people")
        if existing is not None:
            for k in ("trackers", "calendars", "tags", "access_users"):
                if k not in body:
                    setattr(p, k, getattr(existing, k))
        if "access_users" in body:
            p.access_users = self._check_access_users(body.get("access_users"), p.id)
        elif p.nfc_user:
            p.access_users = self._check_access_users([*p.access_users, p.nfc_user], p.id)
        p.nfc_user = ""
        p.irk = existing.irk if existing else ""  # a legacy key stays until the owner deletes it – never a new one
        self.store.put_obj(KIND, p.id, asdict(p))
        return p

    def _check_access_users(self, values: object, pid: str) -> list[str]:
        if not isinstance(values, list) or len(values) > 10:
            raise ValueError("access_users: list with at most 10 entries")
        out: list[str] = []
        for v in values:
            if not isinstance(v, str) or not NFC_RE.match(v.strip()):
                raise ValueError("access_users: letters, digits, space, . _ - (max 40)")
            v = v.strip()
            if any(o.id != pid and v.lower() in (x.lower() for x in o.access_users) for o in self.all()):
                raise ValueError("access user already belongs to another person")
            if v.lower() in (x.lower() for x in self.shared_access()):
                raise ValueError("access user is a shared household code")
            if v not in out:
                out.append(v)
        return out

    def migrate(self) -> None:
        """≤ 0.4.2 → 0.5: single NFC user → list. (Legacy IRKs stay until the owner deletes them, see irks().)"""
        for p in self.all():
            raw = self.store.get_obj(KIND, p.id) or {}
            if raw.get("nfc_user"):
                p.nfc_user = ""
                self.store.put_obj(KIND, p.id, asdict(p))

    # --- owners: Setup decides who a source belongs to ---
    def owner_of(self, entity_id: str) -> str:
        for p in self.all():
            if entity_id in p.trackers or entity_id in p.calendars or entity_id in p.tags:
                return p.id
        return "household" if entity_id in self.household_calendars() else ""

    def owners(self) -> dict[str, str]:
        out = {e: "household" for e in self.household_calendars()}
        for p in self.all():
            for e in p.trackers + p.calendars + p.tags:
                out[e] = p.id
        return out

    def household_calendars(self) -> list[str]:
        try:
            v = json.loads(self.store.get_value("household_calendars") or "[]")
        except ValueError:
            return []
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    def set_owner(self, entity_id: object, owner: object) -> dict:
        """Assign a tracker or calendar to a person, to the household (calendars only) or to nobody ("")."""
        if not isinstance(entity_id, str) or not ENTITY_RE.match(entity_id):
            raise ValueError("invalid entity_id")
        if not isinstance(owner, str) or (owner not in ("", "household") and self.get(owner) is None):
            raise ValueError("unknown person")
        is_cal = entity_id.startswith("calendar.")
        if owner == "household" and not is_cal:
            raise ValueError("only calendars can belong to the whole household")
        if not is_cal and not entity_id.startswith(("device_tracker.", "person.", "binary_sensor.", "sensor.")):
            raise ValueError("this entity cannot belong to a person")
        for p in self.all():
            changed = False
            for k in ("trackers", "calendars", "tags"):
                lst = getattr(p, k)
                if entity_id in lst:
                    setattr(p, k, [x for x in lst if x != entity_id])
                    changed = True
            if p.id == owner:
                key = "calendars" if is_cal else "trackers"
                if len(getattr(p, key)) >= MAX_LINKS:
                    raise ValueError(f"at most {MAX_LINKS} per person")
                setattr(p, key, [*getattr(p, key), entity_id])
                changed = True
            if changed:
                self.store.put_obj(KIND, p.id, asdict(p))
        hc = [x for x in self.household_calendars() if x != entity_id]
        if owner == "household":
            hc.append(entity_id)
        self.store.set_value("household_calendars", json.dumps(hc))
        return {"entity_id": entity_id, "owner": owner}

    # --- access values: Setup maps what an identity entity reports ---
    def access_target(self, reported: str | None) -> str | None:
        """person id, "household", "ignore", "denied" or None (authorised but not assigned)."""
        if not reported:
            return "ignore"
        if DENIED_RE.search(reported):
            return "denied"
        low = reported.strip().lower()
        if low in (x.lower() for x in self.ignored_access()):
            return "ignore"
        for p in self.all():
            if any(low == u.lower() or access_match(u, reported) for u in p.access_users):
                return p.id
        if any(low == u.lower() or access_match(u, reported) for u in self.shared_access()):
            return "household"
        return None

    def access_map(self) -> dict[str, str]:
        out = {v: "household" for v in self.shared_access()}
        out.update({v: "ignore" for v in self.ignored_access()})
        for p in self.all():
            for u in p.access_users:
                out[u] = p.id
        return out

    def ignored_access(self) -> list[str]:
        try:
            v = json.loads(self.store.get_value("access_ignored") or "[]")
        except ValueError:
            return []
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    def map_access(self, value: object, target: object) -> dict:
        """target: person id, "household", "ignore" or "" (not assigned – still counts as authorised)."""
        if not isinstance(value, str) or not NFC_RE.match(value.strip()):
            raise ValueError("value: letters, digits, space, . _ - (max 40)")
        if not isinstance(target, str) or (target not in ("", "household", "ignore") and self.get(target) is None):
            raise ValueError("unknown target")
        v = value.strip()
        for p in self.all():
            if any(u.lower() == v.lower() for u in p.access_users):
                p.access_users = [u for u in p.access_users if u.lower() != v.lower()]
                self.store.put_obj(KIND, p.id, asdict(p))
        shared = [x for x in self.shared_access() if x.lower() != v.lower()]
        ignored = [x for x in self.ignored_access() if x.lower() != v.lower()]
        if target == "household":
            shared.append(v)
        elif target == "ignore":
            ignored.append(v)
        self.store.set_value("shared_access", json.dumps(shared[:20]))
        self.store.set_value("access_ignored", json.dumps(ignored[:50]))
        if target not in ("", "household", "ignore"):
            p = self.get(target)
            if p is not None:
                if len(p.access_users) >= 10:
                    raise ValueError("at most 10 access users per person")
                p.access_users = [*p.access_users, v]
                self.store.put_obj(KIND, p.id, asdict(p))
        return {"value": v, "target": target}

    # --- legacy Bluetooth keys (≤ 0.6): only listed masked and deleted – since 0.7 they live in HA ---
    def irks(self) -> list[dict]:
        """Legacy keys still stored in Bifrost – masked. Since 0.7 they belong into HA (Private BLE Device)."""
        out = [{"id": d.get("id"), "label": d.get("label", ""), "owner": d.get("owner", ""), "key": mask(d.get("key", "")), "has_key": bool(d.get("key"))} for d in self.store.list_objs("irk")]
        out += [{"id": "person_" + p.id, "label": p.name, "owner": p.id, "key": mask(p.irk), "has_key": True} for p in self.all() if p.irk]
        return out

    def delete_all_irks(self) -> dict:
        n = self.store.del_kind("irk")
        for p in self.all():
            if p.irk:
                p.irk = ""
                self.store.put_obj(KIND, p.id, asdict(p))
                n += 1
        return {"deleted": n}

    def delete_irk(self, iid: object) -> dict:
        if not isinstance(iid, str) or not ID_RE.match(iid):
            raise ValueError("invalid id")
        return {"deleted": self.store.del_obj("irk", iid)}

    def delete(self, pid: str) -> bool:
        for d in self.store.list_objs("irk"):
            if d.get("owner") == pid:
                self.store.put_obj("irk", d["id"], {**d, "owner": ""})
        return self.store.del_obj(KIND, pid)

    # --- access system: entities that report who unlocked ---
    def access_entities(self) -> list[str]:
        try:
            v = json.loads(self.store.get_value("access_entities") or "[]")
        except ValueError:
            return []
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    def set_access_entities(self, ids: object) -> list[str]:
        out = validate_access_entities(ids)
        self.store.set_value("access_entities", json.dumps(out))
        return out

    # --- shared access: a code or tag the whole household uses, assigned to nobody ---
    def shared_access(self) -> list[str]:
        try:
            v = json.loads(self.store.get_value("shared_access") or "[]")
        except ValueError:
            return []
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    def set_shared_access(self, names: object) -> list[str]:
        if not isinstance(names, list) or len(names) > 10:
            raise ValueError("names: list with at most 10 entries")
        out: list[str] = []
        for n in names:
            if not isinstance(n, str) or not NFC_RE.match(n.strip()):
                raise ValueError("names: letters, digits, space, . _ - (max 40)")
            if any(u.lower() == n.strip().lower() for p in self.all() for u in p.access_users):
                raise ValueError("names: already belongs to a person")
            if n.strip() not in out:
                out.append(n.strip())
        self.store.set_value("shared_access", json.dumps(out))
        return out


ACCESS_DOMAINS = ("sensor.", "input_text.", "text.", "event.", "lock.", "alarm_control_panel.", "binary_sensor.")


def validate_access_entities(ids: object) -> list[str]:
    if not isinstance(ids, list) or len(ids) > 5:
        raise ValueError("entities: list with at most 5 entries")
    out: list[str] = []
    for e in ids:
        if not isinstance(e, str) or not ENTITY_RE.match(e) or not e.startswith(ACCESS_DOMAINS):
            raise ValueError("entities: invalid entity id")
        if e not in out:
            out.append(e)
    return out


def access_match(name: str, reported: str | None) -> bool:
    """True when the access system reported this user (whole word, case-insensitive)."""
    if not name or not reported:
        return False
    return re.search(r"(?<![\w])" + re.escape(name.lower()) + r"(?![\w])", reported.lower()) is not None


def _src_state(state: str | None) -> str:
    s = (state or "").lower()
    if s in ("", "unavailable", "unknown", "none"):
        return UNCLEAR
    if s in ("home", "on", "detected", "present"):
        return HOME
    return AWAY


def ledger(persons: list[Person], states: dict[str, str | None], strengths: dict[str, str] | None = None, unknown_min: int = 0) -> dict:
    """Who is home right now? Pure function, explained per person."""
    strengths = strengths or {}
    rows: list[dict] = []
    for p in persons:
        srcs = p.sources
        vals = {e: _src_state(states.get(e)) for e in srcs}
        homes = [e for e, v in vals.items() if v == HOME]
        if homes:
            best = max((strengths.get(e, WEAK) for e in homes), key=lambda s: {STRONG: 3, MEDIUM: 2, WEAK: 1}[s])
            rows.append({"id": p.id, "name": p.name, "kind": p.kind, "state": HOME, "strength": best, "reason": "source_home", "source": homes[0]})
        elif srcs and all(v == AWAY for v in vals.values()):
            rows.append({"id": p.id, "name": p.name, "kind": p.kind, "state": AWAY, "strength": None, "reason": "sources_away", "source": srcs[0]})
        elif srcs:
            rows.append({"id": p.id, "name": p.name, "kind": p.kind, "state": UNCLEAR, "strength": None, "reason": "source_unavailable", "source": None})
        else:
            rows.append({"id": p.id, "name": p.name, "kind": p.kind, "state": UNCLEAR, "strength": None, "reason": "no_source", "source": None})
    # people who never stay alone leave with the others: if every person with a source is away, they are away too
    tracked = [r for r in rows if r["reason"] in ("source_home", "sources_away")]
    others_away = bool(tracked) and all(r["state"] == AWAY for r in tracked)
    by_id = {p.id: p for p in persons}
    for r in rows:
        if r["reason"] == "no_source" and not by_id[r["id"]].may_be_alone and others_away:
            r.update(state=AWAY, reason="never_alone")
    household = [r for r in rows if r["kind"] == "household"]
    visitors_home = [r for r in rows if r["kind"] == "visitor" and r["state"] == HOME]
    all_away = all(r["state"] == AWAY for r in household) and not visitors_home and unknown_min == 0
    return {
        "people": rows,
        "unknown_min": max(0, int(unknown_min)),
        "all_away": all_away if rows else None,  # None = no people defined (fallback to rules)
        "unclear": [r["name"] for r in rows if r["state"] == UNCLEAR],
        "home": [r["name"] for r in rows if r["state"] == HOME],
    }
