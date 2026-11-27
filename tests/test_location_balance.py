import base64
from datetime import UTC, datetime, timedelta

import pytest
from bifrost_app import balance, location

T = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
P = datetime.fromisoformat


def test_fingerprints_learn_places_and_say_unknown_when_far():
    fp = location.Fingerprints()
    for i in range(8):
        fp.add("inside", {"scanner_house": -55 - i % 3, "scanner_pool": -90})
        fp.add("garden", {"scanner_house": -88, "scanner_pool": -60 - i % 3})
    assert fp.fit() == {"inside": 8, "garden": 8}
    assert fp.locate({"scanner_house": -57, "scanner_pool": -92})["place"] == "inside"
    assert fp.locate({"scanner_house": -90, "scanner_pool": -61})["place"] == "garden"
    assert fp.locate({"scanner_garage": -40})["place"] == "unknown"
    assert location.Fingerprints().locate({"a": -50})["place"] == "unknown"


def test_access_point_place():
    assert location.ap_place({"ap_mac": "AA:BB"}, {"aa:bb": "garage"}) == "garage"
    assert location.ap_place({}, {}) is None


def test_co2_trend():
    falling = [(T + timedelta(minutes=15 * i), 900 - 20 * i) for i in range(10)]
    assert location.co2_trend(falling)["hint"] == "falling"
    assert location.co2_trend(falling[:3])["hint"] is None


def test_floorplan_validation():
    png = location.PNG_MAGIC + b"0" * 20
    assert location.validate_floorplan(base64.b64encode(png).decode())[1] == "image/png"
    with pytest.raises(ValueError):
        location.validate_floorplan(base64.b64encode(b"<svg onload=alert(1)>").decode())
    with pytest.raises(ValueError):
        location.validate_floorplan("not base64!!")


def test_kpis_gate_and_signal():
    labels = [{"ts": T.isoformat(), "said": "away", "actual": "home"}, {"ts": T.isoformat(), "said": "away", "actual": "away"}]
    decisions = [{"ts": (T - timedelta(hours=5)).isoformat(), "state": "away"}, {"ts": (T - timedelta(hours=2)).isoformat(), "state": "home"}]
    k = balance.kpis(labels, decisions, [{"ts": T.isoformat(), "answer": "yes"}], T, P)
    assert k["wrong_empty"] == 1 and k["confirmed_empty"] == 1 and k["empty_hours"] == 3.0 and k["false_suspicions"] == 1
    g = balance.gate(T - timedelta(days=40), 25, k, 95, T)
    assert not g["passed"] and [c["id"] for c in g["checks"] if not c["ok"]] == ["wrong_empty"]
    ok = balance.gate(T - timedelta(days=40), 25, {"wrong_empty": 0}, 95, T)
    assert ok["passed"]
    assert balance.signal(True, True, "away", 95, True)
    assert not balance.signal(False, True, "away", 95, True)  # option off by default
    assert not balance.signal(True, True, "away", 80, True)
    assert not balance.signal(True, False, "away", 99, True)
