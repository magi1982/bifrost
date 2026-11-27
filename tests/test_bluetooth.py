import pytest

from bifrost_app import bluetooth as bt
from bifrost_app import housemap as hm
from bifrost_app.blehub import BleHub, mac_match


class Store:
    def __init__(self):
        self.v = {}

    def get_value(self, k):
        return self.v.get(k)

    def set_value(self, k, v):
        self.v[k] = v


def test_classify_short_labels_and_guess():
    assert bt.classify({"manufacturer_data": {"76": "1005031c"}}) == ("iPhone", "phone", True)
    assert bt.classify({"manufacturer_data": {"76": "07190220"}}) == ("AirPods", "audio", False)
    assert bt.classify({"manufacturer_data": {"76": "12190000"}})[0] == "Find My"
    assert bt.classify({"name": "[TV] Samsung 7 Series", "manufacturer_data": {"117": "42"}}) == ("Samsung TV", "tv", False)
    assert bt.classify({"service_uuids": ["0000fe2c-0000-1000-8000-00805f9b34fb"]}) == ("Android", "android", True)
    assert bt.classify({"name": "ATC_Keller", "service_uuids": ["0000fcd2-0000-1000-8000-00805f9b34fb"]}) == ("ATC_Keller", "sensor", False)
    assert bt.classify({"name": "Galaxy Watch6"})[1] == "watch"
    assert bt.classify({}) == ("Bluetooth", "device", True)
    assert bt.classify({"manufacturer_data": {"x": "zz", "76": "zz"}})[0] == "Apple"  # garbage does not crash


def test_rotating_addresses_are_kept_only_briefly():
    assert bt.is_rotating("5A:11:22:33:44:55") and not bt.is_rotating("C4:7D:CC:10:20:30")
    t = bt.Tracker()
    t.ingest([{"address": "5A:11:22:33:44:55", "source": "AA:00:00:00:00:01", "rssi": -60}, {"address": "C4:7D:CC:10:20:30", "source": "AA:00:00:00:00:01", "rssi": -50}], now=1000)
    assert len(t.present(1000)) == 2 and t.present(1000 + bt.PRESENT_S + 1) == []
    dropped = t.prune(1000 + 16 * 60)
    assert "5A:11:22:33:44:55" not in t.devices and dropped == []
    assert t.prune(1000 + 91 * 86400) == ["C4:7D:CC:10:20:30"]


def test_ingest_rejects_garbage():
    t = bt.Tracker()
    n = t.ingest(
        [{"address": "x", "source": "s", "rssi": -50}, {"address": "AA:BB:CC:DD:EE:FF", "source": "", "rssi": -50}, {"address": "AA:BB:CC:DD:EE:FF", "source": "S", "rssi": "loud"}, None or {}]
    )
    assert n == 0 and t.devices == {}
    t.ingest([{"address": "aa:bb:cc:dd:ee:ff", "source": "S1", "rssi": 50}])
    assert t.devices["AA:BB:CC:DD:EE:FF"].rssi["S1"] == 0.0  # clamped


def test_centroid_and_fingerprints():
    scanners = {"A": {"floor": "EG", "x": 0, "y": 0}, "B": {"floor": "EG", "x": 10, "y": 0}, "C": {"floor": "OG", "x": 5, "y": 5}}
    p = bt.centroid({"A": -50, "B": -80, "C": -90}, scanners)
    assert p["floor"] == "EG" and p["x"] < 2
    samples = [
        {"floor": "EG", "x": 1, "y": 1, "vec": {"A": -50, "B": -80, "C": -85}},
        {"floor": "EG", "x": 2, "y": 1, "vec": {"A": -52, "B": -78, "C": -86}},
        {"floor": "EG", "x": 9, "y": 1, "vec": {"A": -80, "B": -50, "C": -85}},
        {"floor": "OG", "x": 5, "y": 5, "vec": {"A": -75, "B": -76, "C": -50}},
        {"floor": "OG", "x": 6, "y": 5, "vec": {"A": -76, "B": -75, "C": -52}},
        {"floor": "OG", "x": 4, "y": 5, "vec": {"A": -74, "B": -77, "C": -51}},
    ]
    k = bt.locate({"A": -74, "B": -76, "C": -51}, scanners, samples)
    assert k["method"] == "fingerprint" and k["floor"] == "OG"
    acc = bt.accuracy(samples)
    assert acc["OG"]["floor_hit"] == 100 and acc["OG"]["error_m"] is not None


def test_proposals_cover_every_room():
    m = {"rooms": [{"area": "Hall", "rects": [[0, 0, 2, 2]]}, {"area": "Living", "rects": [[2, 0, 6, 6]]}, {"area": "Pool", "outside": True, "rects": [[10, 0, 3, 3]]}]}
    pts = bt.proposals(m)
    assert {p["area"] for p in pts} == {"Hall", "Living", "Pool"} and sum(1 for p in pts if p["area"] == "Living") >= 3
    assert any(p["outside"] for p in pts)


def test_hysteresis():
    h = bt.Hysteresis(20, 60)
    assert not h.update("z", True, 0) and not h.update("z", True, 10) and h.update("z", True, 21)
    assert h.update("z", False, 30) and h.update("z", False, 80) and not h.update("z", False, 91)


def test_calibration_collects_median_per_scanner():
    t = bt.Tracker()
    c = bt.Calibration(t)
    c.start("C4:7D:CC:10:20:30", "EG", 1.0, 2.0, now=100)
    for i in range(5):
        t.ingest([{"address": "C4:7D:CC:10:20:30", "source": s, "rssi": r} for s, r in (("A", -60), ("B", -70), ("C", -80))], now=101 + i)
    t.ingest([{"address": "11:11:11:11:11:11", "source": "A", "rssi": -20}], now=102)  # other devices are ignored
    assert c.status(105)["running"] and c.finish(105) is None
    s = c.finish(100 + bt.CAL_SECONDS + 1)
    assert s["vec"] == {"A": -60, "B": -70, "C": -80} and s["quality"] == "good" and s["scanners"] == 3


def test_mac_match_and_zone_validation():
    assert mac_match("AA:BB:CC:00:00:03", ["aa:bb:cc:00:00:01"]) and not mac_match("AA:BB:CC:00:00:09", ["aa:bb:cc:00:00:01"])
    fa = {"EG": ["Living"]}
    _, m = hm.validate_map({"floor": "EG", "w": 10, "h": 8, "zones": [{"name": "Sofa", "rects": [[1, 1, 2, 2]]}]}, fa)
    assert m["zones"] == [{"name": "Sofa", "rects": [[1, 1, 2, 2]]}]
    for bad in ([{"name": "<x>", "rects": [[1, 1, 1, 1]]}], [{"name": "A", "rects": []}], [{"name": "A", "rects": [[1, 1, 1, 1]]}, {"name": "A", "rects": [[2, 2, 1, 1]]}]):
        with pytest.raises(ValueError):
            hm.validate_map({"floor": "EG", "w": 10, "h": 8, "zones": bad}, fa)


def test_hub_settings_hiding_and_calibration_validation():
    hub = BleHub(Store())
    with pytest.raises(ValueError):
        hub.set_settings({"on": "yes"})
    with pytest.raises(ValueError):
        hub.set_settings({"address": "nope", "hidden": True})
    hub.set_settings({"address": "c4:7d:cc:10:20:30", "hidden": True, "hide_house": True})
    assert "C4:7D:CC:10:20:30" in hub.hidden and hub.settings["hide_house"]
    maps = {"EG": {"w": 10, "h": 8, "rooms": [], "devices": []}}
    with pytest.raises(ValueError):
        hub.cal_start({"device": "C4:7D:CC:10:20:30", "floor": "OG", "x": 1, "y": 1}, maps, {})
    with pytest.raises(ValueError):
        hub.cal_start({"device": "C4:7D:CC:10:20:30", "floor": "EG", "x": 99, "y": 1}, maps, {})
    with pytest.raises(ValueError):
        hub.cal_start({"device": "C4:7D:CC:10:20:30", "floor": "EG", "x": 1, "y": 1}, maps, {})  # not heard
    hub.tracker.ingest([{"address": "C4:7D:CC:10:20:30", "source": "A", "rssi": -60}])
    assert hub.cal_start({"device": "c4:7d:cc:10:20:30", "floor": "EG", "x": 1, "y": 1}, maps, {})["running"]
    with pytest.raises(ValueError):
        hub.cal_delete(5)


def test_service_bluetooth_zones_and_person_location(tmp_path):
    from demo import IRK_ADDR, build, demo_bluetooth

    svc = build(str(tmp_path / "h.db"))
    demo_bluetooth(svc)
    svc.evaluate()
    v = svc.bluetooth_view()
    phone = next(r for r in v["devices"] if r["address"] == IRK_ADDR)
    assert phone["irk"] and phone["person"] == "Person A" and phone["pos"] and phone["room"]
    assert all(s["placed"] for s in v["scanners"])
    pub = svc.client.published
    assert "binary_sensor.bifrost_zone_sofa" in pub and pub["binary_sensor.bifrost_zone_sofa"][1]["device_class"] == "occupancy"
    assert pub["sensor.bifrost_person_a_location"][0] == phone["room"]
    assert "sensor.bifrost_kind_a_location" not in pub  # no IRK phone → no location entity
    live = svc.live_view()
    assert any(r["address"] == IRK_ADDR for r in live["ble"]) and live["placeable"]["ble"]
    cal = svc.calib_view()
    assert cal["points"]["Ground floor"] and any(d["irk"] for d in cal["devices"])
    svc.set_bluetooth({"on": False})
    svc.evaluate()
    assert svc.bluetooth_view()["devices"] == []


def test_missing_gateways_with_reason():
    hub = BleHub(Store())
    hub.tracker.sources["AA:BB:CC:00:00:03"] = {"name": "x", "last": 0, "count": 1}
    rows = hub.missing(
        [
            {"name": "Hall", "model": "Shelly Plus 1", "macs": ["aa:bb:cc:00:00:01"]},  # is a gateway (mac + 2)
            {"name": "Bath light", "model": "SHSW-1", "macs": ["11:22:33:44:55:66"]},
            {"name": "Socket", "model": "Shelly Plus Plug S", "macs": ["11:22:33:44:55:77"]},
            {"name": "Proxy", "manufacturer": "Espressif", "model": "esp32", "macs": ["22:22:33:44:55:66"]},
        ]
    )
    assert {r["name"]: r["reason"] for r in rows} == {"Bath light": "no_ble", "Socket": "enable", "Proxy": "esphome"}
