"""Setup optimisations: where the current category/role of a signal differs from what works best.

Every finding is one suggestion for one entity; the user applies or dismisses each one.
Rules are generic (device class, domain, name keywords) and use what Bifrost learned
(door roles from the live stream, the sensor doctor) once it is available.
"""

from __future__ import annotations

import re

DOOR_WORDS = re.compile(r"t(ü|ue)r|\btor\b|(garagen|garten|hof|einfahrts|haus)tor|door|gate|pforte", re.I)
OUTSIDE_DOOR_WORDS = re.compile(r"haust|hausein|eingang|front|entrance|garage|terrass|terrace|sitzplatz|balkon|balcony|garten|garden|keller.?aussen|aussent|patio", re.I)
WINDOW_WORDS = re.compile(r"fenster|window|dachfenster|velux", re.I)
PASSAGE_WORDS = re.compile(r"schiebe|\bhst\b|bodentief|terrass|terrace|garten|garden|sitzplatz|balkon|balcony|patio|sliding|french", re.I)
GUEST_WORDS = re.compile(r"\bgast|gäste|guest", re.I)
SLEEP_WORDS = re.compile(r"schlaf|sleep|nachtmodus|night.?mode|bettzeit|bedtime", re.I)
OPENING_CLASSES = {"door", "garage_door", "window", "opening"}
MOTION_CLASSES = {"motion", "occupancy", "presence"}


def _sug(e: dict, key: str, status: str | None = None, category: str | None = None, role: str | None = None, detail: str = "") -> dict:
    return {
        "entity_id": e["entity_id"],
        "name": e.get("name") or e["entity_id"],
        "key": key,
        "detail": detail,
        "current": {"status": e.get("status"), "category": e.get("category"), "role": e.get("role")},
        "suggest": {"status": status or e.get("status"), "category": category or e.get("category"), "role": role or e.get("role")},
    }


def suggestions(entities: list[dict], door_roles: dict[str, dict] | None = None, doctor: list[dict] | None = None, dismissed: set[str] | None = None) -> list[dict]:  # noqa: C901
    """All optimisations for the scanned entities (dicts as in the Setup view)."""
    door_roles = door_roles or {}
    problems = {p["entity_id"]: p for p in doctor or []}
    dismissed = dismissed or set()
    out: list[dict] = []
    for e in entities:
        eid, dc, domain = e["entity_id"], (e.get("device_class") or "").lower(), e.get("domain") or e["entity_id"].split(".", 1)[0]
        text = f"{e.get('name') or ''} {eid}"
        status, cat, role = e.get("status"), e.get("category"), e.get("role")
        used = status == "included"
        found: list[dict] = []

        if e.get("disabled") and used:
            found.append(_sug(e, "disabled_in_ha", status="ignored"))
        elif domain == "binary_sensor" and dc in OPENING_CLASSES:
            learned = (door_roles.get(eid) or {}).get("role")
            is_door = dc in ("door", "garage_door") or bool(DOOR_WORDS.search(text))
            is_window = not is_door and (dc == "window" or bool(WINDOW_WORDS.search(text)))
            passage = is_window and bool(PASSAGE_WORDS.search(text))  # floor-length window / sliding door to garden or terrace
            unknown = learned is None or learned == "unknown"
            outside = learned == "entrance" or unknown and is_door and bool(OUTSIDE_DOOR_WORDS.search(text))
            if (is_door or learned == "entrance") and outside and (role != "Trigger" or cat != "openings" or not used):
                found.append(_sug(e, "entry_door", status="included", category="openings", role="Trigger", detail="learned" if learned == "entrance" else ""))
            elif passage and unknown:
                if role != "Trigger" or not used:
                    found.append(_sug(e, "passage_window", status="included", category="openings", role="Trigger"))
            elif (is_door or passage) and learned == "inside_only" and role == "Trigger":
                found.append(_sug(e, "inner_door", category="openings", role="Evidence"))
            elif is_window and not passage and used and (role != "Evidence" or cat != "openings"):
                found.append(_sug(e, "window", category="openings", role="Evidence"))
        elif domain == "binary_sensor" and dc in MOTION_CLASSES:
            if not used and status != "ignored":
                found.append(_sug(e, "motion_off", status="included", category="motion", role=role if role in ("Evidence", "Noise") else "Evidence"))
            elif used and (cat != "motion" or role not in ("Evidence", "Noise")):
                found.append(_sug(e, "motion", category="motion", role="Evidence"))
        elif domain in ("input_boolean", "switch") and used:
            if (GUEST_WORDS.search(text) or SLEEP_WORDS.search(text)) and role != "Blocker":
                found.append(_sug(e, "mode", category="modes", role="Blocker"))
        elif domain in ("vacuum", "lawn_mower") and used and role != "Noise":
            found.append(_sug(e, "robot", category="vehicles", role="Noise"))
        elif domain == "alarm_control_panel" and used and role != "Truth":
            found.append(_sug(e, "alarm", category="security", role="Truth"))
        elif e.get("guess_role") == "Identity" and role != "Identity" and status != "ignored":
            found.append(_sug(e, "identity", status="included", category="security", role="Identity"))
        elif domain == "calendar" and used and role != "Context":
            found.append(_sug(e, "calendar", category="calendar", role="Context"))

        if used and not cat and not found:
            g = e.get("guess_category")
            if g:
                found.append(_sug(e, "no_category", category=g))
        p = problems.get(eid)
        if used and p and p.get("problem") in ("dead", "gaps") and not found:
            found.append(_sug(e, "doctor_" + p["problem"], status="ignored", detail=p.get("detail", "")))

        out += [f for f in found if f"{eid}|{f['key']}" not in dismissed and f["suggest"] != f["current"]]
    order = {"entry_door": 0, "passage_window": 1, "motion_off": 1, "disabled_in_ha": 2, "window": 3, "motion": 3, "mode": 4, "inner_door": 5}
    return sorted(out, key=lambda x: (order.get(x["key"], 9), x["name"].lower()))
