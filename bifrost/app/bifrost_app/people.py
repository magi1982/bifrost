"""People (0.4) – persons are defined in Bifrost only, not as HA persons or users.

Per person the owner links whatever exists: phone trackers, BLE identity (iPhone IRK), calendars,
an NFC user name from the alarm keypad, tags – or nothing (e.g. a child without phone).

The **ledger** answers, every minute, for each person: home / away / unclear – plus
"unknown people: at least N" for entries nothing explains. "Empty" is only allowed when
everybody is away and the unknown counter is 0.

Secrets: an IRK is stored locally only and never returned by the API (only a masked hint).
"""

from __future__ import annotations

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
    nfc_user: str = ""
    irk: str = ""

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
    return Person(**{k: d[k] for k in Person.__dataclass_fields__ if k in d})


def public(p: Person) -> dict:
    """API representation – never contains the IRK itself."""
    d = asdict(p)
    d["irk"] = ("••••" + p.irk[-4:]) if p.irk else ""
    d["has_irk"] = bool(p.irk)
    return d


class PeopleStore:
    def __init__(self, store) -> None:  # noqa: ANN001
        self.store = store

    def all(self) -> list[Person]:
        return [from_dict(d) for d in self.store.list_objs(KIND)]

    def get(self, pid: str) -> Person | None:
        d = self.store.get_obj(KIND, pid)
        return from_dict(d) if d else None

    def save(self, body: dict) -> Person:
        existing = self.get(body.get("id")) if isinstance(body.get("id"), str) else None
        p = validate(body, existing)
        if existing is None and self.get(p.id) is not None:
            raise ValueError("a person with this id exists")
        if existing is None and len(self.all()) >= 30:
            raise ValueError("at most 30 people")
        self.store.put_obj(KIND, p.id, asdict(p))
        return p

    def delete(self, pid: str) -> bool:
        return self.store.del_obj(KIND, pid)


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
