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
