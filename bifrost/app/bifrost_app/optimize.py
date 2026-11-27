"""Setup optimisations: where the category or the on/off of a signal differs from what works best.

Since 0.6 there are no roles to set: the role follows from the category, the name and what Bifrost
learned. Every finding is one suggestion for one entity; the user applies or hides each one.
"""

from __future__ import annotations

import re

GUEST_WORDS = re.compile(r"\bgast|gäste|guest", re.I)
SLEEP_WORDS = re.compile(r"schlaf|sleep|nachtmodus|night.?mode|bettzeit|bedtime", re.I)
AWAY_WORDS = re.compile(r"ferien|urlaub|holiday|vacation|abwesen|away.?mode", re.I)
OPENING_CLASSES = {"door", "garage_door", "window", "opening"}
MOTION_CLASSES = {"motion", "occupancy", "presence"}


def _sug(e: dict, key: str, status: str | None = None, category: str | None = None, detail: str = "") -> dict:
    return {
        "entity_id": e["entity_id"],
        "name": e.get("name") or e["entity_id"],
        "key": key,
        "detail": detail,
        "current": {"status": e.get("status"), "category": e.get("category")},
        "suggest": {"status": status or e.get("status"), "category": category or e.get("category")},
    }


def suggestions(  # noqa: C901
    entities: list[dict], door_roles: dict[str, dict] | None = None, doctor: list[dict] | None = None, dismissed: set[str] | None = None, values: dict[str, dict] | None = None
) -> list[dict]:
    """All optimisations for the scanned entities (dicts as in the Setup view)."""
    values = values or {}
    problems = {p["entity_id"]: p for p in doctor or []}
    dismissed = dismissed or set()
    out: list[dict] = []
    for e in entities:
        eid, dc, domain = e["entity_id"], (e.get("device_class") or "").lower(), e.get("domain") or e["entity_id"].split(".", 1)[0]
        text = f"{e.get('name') or ''} {eid}"
        status, cat = e.get("status"), e.get("category")
        used = status == "included"
        found: list[dict] = []

        if e.get("disabled") and used:
            found.append(_sug(e, "disabled_in_ha", status="ignored"))
        elif domain == "binary_sensor" and dc in OPENING_CLASSES:
            if not used and status != "ignored":
                found.append(_sug(e, "opening_off", status="included", category="openings"))
            elif used and cat != "openings":
                found.append(_sug(e, "opening", category="openings"))
        elif domain == "binary_sensor" and dc in MOTION_CLASSES:
            if not used and status != "ignored":
                found.append(_sug(e, "motion_off", status="included", category="motion"))
            elif used and cat != "motion":
                found.append(_sug(e, "motion", category="motion"))
        elif domain in ("input_boolean", "switch") and used:
            if (GUEST_WORDS.search(text) or SLEEP_WORDS.search(text)) and cat != "mode_home":
                found.append(_sug(e, "mode_home", category="mode_home"))
            elif AWAY_WORDS.search(text) and cat != "mode_away":
                found.append(_sug(e, "mode_away", category="mode_away"))
        elif domain in ("vacuum", "lawn_mower") and used:
            found.append(_sug(e, "robot", status="ignored"))
        elif domain == "alarm_control_panel" and used and cat != "security":
            found.append(_sug(e, "alarm", category="security"))
        elif e.get("guess_category") == "access" and cat != "access" and status != "ignored":
            found.append(_sug(e, "identity", status="included", category="access"))
        elif domain == "calendar" and used and cat != "calendar":
            found.append(_sug(e, "calendar", category="calendar"))

        if used and not cat and not found:
            g = e.get("guess_category")
            if g:
                found.append(_sug(e, "no_category", category=g))
        p = problems.get(eid)
        if used and p and p.get("problem") in ("dead", "gaps") and not found:
            found.append(_sug(e, "doctor_" + p["problem"], status="ignored", detail=p.get("detail", "")))
        v = values.get(eid) or {}
        if used and not found and v.get("verdict") in ("nothing", "slow"):
            # Bifrost learned that this signal brings nothing – it only suggests, the owner decides
            found.append(_sug(e, "value_" + v["verdict"], status="ignored", detail=v.get("reason", "")))

        out += [f for f in found if f"{eid}|{f['key']}" not in dismissed and f["suggest"] != f["current"]]
    order = {"opening_off": 0, "motion_off": 1, "disabled_in_ha": 2, "identity": 3, "mode_home": 4}
    return sorted(out, key=lambda x: (order.get(x["key"], 9), x["name"].lower()))
