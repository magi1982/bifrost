"""People (0.4) – persons are defined in Bifrost only, not as HA persons or users.

Per person the owner links whatever exists: phone trackers, BLE identity (iPhone IRK), calendars,
an NFC user name from the alarm keypad, tags – or nothing (e.g. a child without phone).

The **ledger** answers, every minute, for each person: home / away / unclear – plus
"unknown people: at least N" for entries nothing explains. "Empty" is only allowed when
everybody is away and the unknown counter is 0.

Secrets: an IRK is stored locally only and never returned by the API (only a masked hint).
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
IRK_RE = re.compile(r"^[0-9a-f]{32}$")
NFC_RE = re.compile(r"^[\w .\-]{1,40}$", re.UNICODE)
MAX_LINKS = 10

HOME, AWAY, UNCLEAR = "home", "away", "unclear"
STRONG, MEDIUM, WEAK = "strong", "medium", "weak"

# Strength of an identity signal, by integration of the tracker entity.
STRENGTH_BY_INTEGRATION = {"mobile_app": MEDIUM, "private_ble_device": WEAK, "unifi": WEAK, "bluetooth_le_tracker": WEAK, "ping": WEAK}


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
    irk = body.get("irk")
    if irk is None or irk == "" and existing is not None and body.get("irk_keep", True):
        irk = existing.irk if existing else ""  # empty field in the form = keep the stored key
    if irk == "-":
        irk = ""  # explicit delete
    irk = (irk or "").strip().lower().replace(":", "").replace(" ", "")
    if irk and not IRK_RE.match(irk):
        raise ValueError("irk: 32 hex characters")
    return Person(
        id=pid,
        name=name,
        kind=kind,
        may_be_alone=bool(body.get("may_be_alone", True)),
        trackers=_entities(body.get("trackers"), ("device_tracker.", "person.", "binary_sensor.", "sensor."), "trackers"),
        calendars=_entities(body.get("calendars"), ("calendar.",), "calendars"),
        tags=_entities(body.get("tags"), ("device_tracker.", "binary_sensor.", "sensor."), "tags"),
        nfc_user=nfc.strip(),
        irk=irk,
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
LABEL_RE = re.compile(r"^[\w .\-()]{1,40}$", re.UNICODE)


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
        legacy_irk = p.irk
        p.nfc_user, p.irk = "", ""
        self.store.put_obj(KIND, p.id, asdict(p))
        if legacy_irk and not any(d.get("key") == legacy_irk for d in self.irk_keys()):
            self.save_irk({"label": p.name, "key": legacy_irk, "owner": p.id})
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
        """≤ 0.4.2 → 0.5: single NFC user → list, IRK on the person → IRK objects in Setup."""
        for p in self.all():
            raw = self.store.get_obj(KIND, p.id) or {}
            if raw.get("nfc_user") or raw.get("irk"):
                if raw.get("irk") and not any(d.get("key") == raw["irk"] for d in self.irk_keys()):
                    self.save_irk({"label": p.name, "key": raw["irk"], "owner": p.id})
                p.nfc_user, p.irk = "", ""
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

    # --- Bluetooth keys (iPhone IRK): no HA entity, kept in Setup, never returned in clear ---
    def irks(self) -> list[dict]:
        return [{**d, "key": mask(d.get("key", "")), "has_key": bool(d.get("key"))} for d in self.store.list_objs("irk")]

    def irk_keys(self) -> list[dict]:
        """With the real keys – for internal matching only, never for the API."""
        return self.store.list_objs("irk")

    def save_irk(self, body: object) -> dict:
        if not isinstance(body, dict):
            raise ValueError("invalid body")
        label = body.get("label")
        if not isinstance(label, str) or not LABEL_RE.match(label.strip()):
            raise ValueError("label: 1–40 characters")
        owner = body.get("owner") or ""
        if not isinstance(owner, str) or (owner and self.get(owner) is None):
            raise ValueError("unknown person")
        existing = self.store.get_obj("irk", body["id"]) if isinstance(body.get("id"), str) and ID_RE.match(body["id"]) else None
        key = body.get("key")
        key = (key or "").strip().lower().replace(":", "").replace(" ", "") if isinstance(key, str) else ""
        if not key and existing:
            key = existing.get("key", "")
        if not IRK_RE.match(key):
            raise ValueError("key: 32 hex characters")
        if existing is None:
            if len(self.store.list_objs("irk")) >= 30:
                raise ValueError("at most 30 keys")
            if any(d.get("key") == key for d in self.store.list_objs("irk")):
                raise ValueError("this key exists already")
        iid = existing["id"] if existing else slugify(label)[:30] + "_" + key[-4:]
        d = {"id": iid, "label": label.strip(), "key": key, "owner": owner}
        self.store.put_obj("irk", iid, d)
        return {**d, "key": mask(key), "has_key": True}

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
