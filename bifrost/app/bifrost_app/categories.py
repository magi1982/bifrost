"""Signal categories, roles and statuses used everywhere in Bifrost."""

from __future__ import annotations

CATEGORIES: dict[str, dict[str, str]] = {
    "motion": {"name": "Motion & presence", "icon": "🚶", "desc": "Presence, motion and mmWave sensors"},
    "openings": {"name": "Doors & windows", "icon": "🚪", "desc": "Front door, garage, windows"},
    "manual": {"name": "Manual activity", "icon": "👆", "desc": "Lights, blinds, buttons, thermostats used by a person"},
    "devices": {"name": "People & devices", "icon": "📱", "desc": "Phones and watches via Wi-Fi, Bluetooth, GPS"},
    "network": {"name": "Network", "icon": "🌐", "desc": "Clients per Wi-Fi, traffic"},
    "media": {"name": "Media", "icon": "🎵", "desc": "Speakers, TV, receiver playing"},
    "climate": {"name": "Air & climate", "icon": "🌡️", "desc": "CO₂, humidity, temperature"},
    "energy": {"name": "Energy", "icon": "⚡", "desc": "Base load, appliances, water"},
    "vehicles": {"name": "Vehicles & tags", "icon": "🚗", "desc": "Car beacon, tags, robots, pets"},
    "mode_home": {"name": "Mode: someone home", "icon": "🛋️", "desc": "Guest, sleep or night mode – “empty” is impossible while it is on"},
    "mode_away": {"name": "Mode: away", "icon": "🧳", "desc": "Holiday or away mode – a clue that nobody is home"},
    "calendar": {"name": "Time & calendar", "icon": "📅", "desc": "Calendars, alarm clocks, weather, zones"},
    "security": {"name": "Security", "icon": "🔒", "desc": "Alarm state, locks – confirms afterwards whether the house was empty"},
    "access": {"name": "Access", "icon": "🔑", "desc": "Keypads, NFC, fingerprint, “last user” – who unlocked"},
}

ROLES: dict[str, str] = {
    "Evidence": "says home or away",
    "Trigger": "starts a new check",
    "Context": "changes what is expected",
    "Blocker": "prevents “empty”",
    "Noise": "fakes activity – gets masked",
    "Truth": "proof that teaches Bifrost",
    "Identity": "says who it was",
}

# Status of an entity inside Bifrost
STATUS_INCLUDED = "included"
STATUS_SUGGESTED = "suggested"
STATUS_UNKNOWN = "unknown"
STATUS_IGNORED = "ignored"
STATUSES = (STATUS_INCLUDED, STATUS_SUGGESTED, STATUS_UNKNOWN, STATUS_IGNORED)

# Confidence thresholds for automatic decisions of the classifier
AUTO_INCLUDE = 0.85
SUGGEST = 0.60


def is_valid_category(value: str | None) -> bool:
    """Return True if value is a known category id (or None)."""
    return value is None or value in CATEGORIES


def is_valid_role(value: str | None) -> bool:
    """Return True if value is a known role (or None)."""
    return value is None or value in ROLES


# --- roles are no longer set by the user (0.6): they follow from the category, the name and what Bifrost learned ---
ROLE_BY_CATEGORY = {
    "access": "Identity",
    "mode_home": "Blocker",
    "mode_away": "Context",
    "calendar": "Context",
}


def derive_role(category: str | None, guess_category: str | None, guess_role: str | None, learned_door: str | None = None) -> str | None:
    """Internal role for the engine. The classifier's role is kept when the category is its own guess
    (it knows details like doorbells or outdoor motion); a learned entrance always triggers."""
    if not category:
        return None
    if category in ROLE_BY_CATEGORY:
        return ROLE_BY_CATEGORY[category]
    if category == "openings" and learned_door == "entrance":
        return "Trigger"
    if category == "openings" and learned_door == "inside_only":
        return "Evidence"
    if category == guess_category and guess_role:
        return guess_role
    return "Truth" if category == "security" else "Evidence"
