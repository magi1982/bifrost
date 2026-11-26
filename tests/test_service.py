from datetime import UTC, datetime, timedelta

from bifrost_app.service import BifrostService
from bifrost_app.store import Store

OLD = (datetime.now(UTC) - timedelta(hours=2)).isoformat()


class FakeClient:
    def __init__(self):
        self.published = {}
        self.states = [
            {"entity_id": "person.example_a", "state": "not_home", "last_changed": OLD, "attributes": {"friendly_name": "Person A"}},
            {"entity_id": "binary_sensor.hall_motion", "state": "off", "last_changed": OLD, "attributes": {"device_class": "motion", "friendly_name": "Hall motion"}},
            {"entity_id": "update.core", "state": "off", "last_changed": OLD, "attributes": {}},
            {"entity_id": "sensor.bifrost_home_status", "state": "away", "last_changed": OLD, "attributes": {}},
        ]

    def get_states(self):
        return self.states

    def registries(self):
        return {
            "entities": [{"entity_id": "binary_sensor.hall_motion", "platform": "hue", "area_id": "hall"}, {"entity_id": "light.disabled_lamp", "platform": "hue", "disabled_by": "user"}],
            "devices": [],
            "areas": [{"area_id": "hall", "name": "Hall"}],
        }

    def get_calendar(self, eid, start, end):
        return getattr(self, "calendar_entries", [])

    def set_state(self, eid, state, attrs):
        self.published[eid] = (state, attrs)


def make(tmp_path, **opts):
    client = FakeClient()
    return BifrostService(client, Store(str(tmp_path / "s.db")), {"shadow_mode": True, "publish_entities": True, **opts}), client


def test_scan_classifies_and_skips_own_entities(tmp_path):
    svc, _ = make(tmp_path)
    svc.scan()
    ents = svc.snap.entities
    assert "sensor.bifrost_home_status" not in ents
    assert ents["binary_sensor.hall_motion"].info.area == "Hall"
    assert ents["light.disabled_lamp"].info.disabled and not ents["light.disabled_lamp"].info.available
    view = svc.entities_view()["summary"]
    assert view["total"] == 4 and view["disabled_in_ha"] == 1


def test_evaluate_publishes_entities(tmp_path):
    svc, client = make(tmp_path)
    svc.scan()
    d = svc.evaluate()
    assert d.state == "away"
    assert client.published["binary_sensor.bifrost_house_empty"][0] == "on"
    assert client.published["sensor.bifrost_home_status"][1]["attribution"] == "Bifrost (shadow mode)"
    assert svc.status_view()["decision"]["label"] == "Away"


def test_publish_can_be_disabled(tmp_path):
    svc, client = make(tmp_path, publish_entities=False)
    svc.scan()
    svc.evaluate()
    assert client.published == {}


def test_user_override_persists_across_scans(tmp_path):
    svc, _ = make(tmp_path)
    svc.scan()
    svc.update_entity("binary_sensor.hall_motion", "ignored", None, None)
    svc.scan()
    e = svc.snap.entities["binary_sensor.hall_motion"]
    assert e.status == "ignored" and e.user_set


def test_unknown_entity_override_is_not_stored(tmp_path):
    import pytest

    svc, _ = make(tmp_path)
    svc.scan()
    with pytest.raises(KeyError):
        svc.update_entity("light.does_not_exist", "included", None, None)
    assert "light.does_not_exist" not in svc.store.get_overrides()


def test_vanished_entity_lowers_data_health(tmp_path):
    svc, client = make(tmp_path)
    svc.scan()
    client.states = [s for s in client.states if s["entity_id"] != "binary_sensor.hall_motion"]
    d = svc.evaluate()
    assert d.data_health < 100 and not d.house_empty


def test_guest_mode_persists_and_blocks(tmp_path):
    svc, client = make(tmp_path)
    svc.scan()
    svc.set_guest_mode(True)
    assert svc.evaluate().state == "home"
    assert client.published["binary_sensor.bifrost_guest_mode"][0] == "on"
    svc2 = BifrostService(client, svc.store, {})
    assert svc2.settings.guest_mode


def test_accept_suggestions(tmp_path):
    svc, client = make(tmp_path)
    client.states.append({"entity_id": "calendar.example_work", "state": "off", "last_changed": OLD, "attributes": {}})
    svc.scan()
    assert svc.snap.entities["calendar.example_work"].status == "suggested"
    assert svc.accept_suggestions("calendar") == {"accepted": 1}
    assert svc.snap.entities["calendar.example_work"].status == "included"


def test_views_and_extra_entities(tmp_path):
    svc, client = make(tmp_path)
    svc.scan()
    svc.evaluate()
    dash = svc.dashboard_view()
    assert len(dash["days"]) == 14 and dash["days"][-1]["minutes"]
    tl = svc.timeline_view()
    assert tl["decisions"] and "events" in tl
    assert client.published["sensor.bifrost_person_example_a"][0] == "away"
    assert client.published["binary_sensor.bifrost_anomaly"][0] == "off"


def test_expected_return_from_history(tmp_path):
    from datetime import timedelta

    svc, _ = make(tmp_path)
    now = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0)
    for w in (1, 2, 3):
        day = now - timedelta(days=7 * w)
        svc.store.add_decision(day.replace(hour=7), "away", 90, [])
        svc.store.add_decision(day.replace(hour=17, minute=30 + w), "home", 90, [])
    ret = svc.expected_return(now)
    assert ret is not None and ret.hour == 17 and 30 <= ret.minute <= 33


def _seed_departures(store, n, with_noise=0):
    from datetime import timedelta

    base = datetime.now(UTC).replace(hour=7, minute=0, second=0, microsecond=0) - timedelta(days=n + 1)
    for i in range(n):
        day = base + timedelta(days=i)
        store.add_decision(day, "home", 90, [])
        store.add_event(day + timedelta(minutes=10), "binary_sensor.front_door", "Front door", "openings", "Trigger", "on")
        store.add_event(day + timedelta(minutes=14), "person.example_a", "Person A", "devices", "Evidence", "not_home")
        store.add_decision(day + timedelta(minutes=20), "leaving", 60, [])
        store.add_decision(day + timedelta(minutes=40), "away", 90, [])
        store.add_decision(day + timedelta(hours=9), "home", 90, [])
    return base


def test_learn_job_finds_pattern_and_drift(tmp_path):
    svc, client = make(tmp_path)
    svc.scan()
    _seed_departures(svc.store, 7)
    svc.learn_job(datetime.now(UTC))
    pats = svc.patterns_view()["patterns"]
    dep = [p for p in pats if p["outcome"] == "departure"]
    assert dep and dep[0]["status"] == "suggested" and dep[0]["support"] == 7
    assert [s["entity_id"] for s in dep[0]["steps"]] == ["binary_sensor.front_door", "person.example_a"]
    pid = dep[0]["id"]
    svc.set_pattern(pid, "enabled")
    svc.evaluate()
    assert f"binary_sensor.bifrost_pattern_{pid}" in client.published
    # drift: the door now opens often without anyone leaving -> precision drops -> "changed"
    from datetime import timedelta

    for i in range(6):
        t = datetime.now(UTC) - timedelta(hours=3 + i * 5)
        svc.store.add_event(t, "binary_sensor.front_door", "Front door", "openings", "Trigger", "on")
        svc.store.add_event(t + timedelta(minutes=4), "person.example_a", "Person A", "devices", "Evidence", "not_home")
    svc.learn_job(datetime.now(UTC))
    st = {p["id"]: p["status"] for p in svc.patterns_view()["patterns"]}
    assert st[pid] == "changed"


def test_calendar_learning_without_titles(tmp_path):
    import json
    from datetime import timedelta

    svc, client = make(tmp_path)
    client.states.append({"entity_id": "calendar.example_work", "state": "on", "last_changed": OLD, "attributes": {"message": "Office day Zurich"}})
    svc.scan()
    svc.update_entity("calendar.example_work", "included", None, None)
    entries = []
    base = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=10)
    for i in range(4):
        st = base + timedelta(days=i)
        svc.store.add_decision(st - timedelta(hours=1), "home", 90, [])
        svc.store.add_decision(st, "away", 90, [])
        svc.store.add_decision(st + timedelta(hours=8), "home", 90, [])
        entries.append({"summary": "Office day Zurich", "start": {"dateTime": st.isoformat()}, "end": {"dateTime": (st + timedelta(hours=8)).isoformat()}})
    client.calendar_entries = entries
    svc.learn_job(datetime.now(UTC))
    view = svc.calendars_view()
    kws = {k["keyword"]: k for k in view["calendars"][0]["insights"]}
    assert kws["office"]["means_away"] and kws["office"]["away_share"] == 100
    raw = json.dumps(svc.store.get_calendar_stats())
    assert "Office day Zurich" not in raw  # full titles are never stored
    d = svc.evaluate()
    assert any("usually away" in r for r in d.reasons)
    assert not any("Office day Zurich" in r for r in d.reasons)  # the title itself is never echoed


def test_calendar_learning_can_be_switched_off(tmp_path):
    svc, client = make(tmp_path, learn_calendars=False)
    svc.scan()
    client.calendar_entries = [{"summary": "x", "start": {"dateTime": "2026-01-01T08:00:00+00:00"}, "end": {"dateTime": "2026-01-01T09:00:00+00:00"}}]
    svc.learn_job(datetime.now(UTC))
    assert svc.store.get_calendar_stats() == {}
