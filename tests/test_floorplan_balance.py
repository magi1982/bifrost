import base64
from datetime import UTC, datetime, timedelta

import pytest

from bifrost_app import balance, floorplan

T = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
P = datetime.fromisoformat


def test_floorplan_validation():
    png = floorplan.PNG_MAGIC + b"0" * 20
    assert floorplan.validate_floorplan(base64.b64encode(png).decode())[1] == "image/png"
    with pytest.raises(ValueError):
        floorplan.validate_floorplan(base64.b64encode(b"<svg onload=alert(1)>").decode())
    with pytest.raises(ValueError):
        floorplan.validate_floorplan("not base64!!")


def test_kpis_gate_and_signal():
    labels = [{"ts": T.isoformat(), "said": "away", "actual": "home"}, {"ts": T.isoformat(), "said": "away", "actual": "away"}]
    decisions = [{"ts": (T - timedelta(hours=5)).isoformat(), "state": "away"}, {"ts": (T - timedelta(hours=2)).isoformat(), "state": "home"}]
    k = balance.kpis(labels, decisions, [{"ts": T.isoformat(), "answer": "yes"}], T, P)
    assert k["wrong_empty"] == 1 and k["confirmed_empty"] == 1 and k["empty_hours"] == 3.0 and k["false_suspicions"] == 1
    g = balance.gate(T - timedelta(days=40), 25, k, 95, T)
    assert not g["passed"] and [c["id"] for c in g["checks"] if not c["ok"]] == ["wrong_empty"]
    ok = balance.gate(T - timedelta(days=40), 25, {"wrong_empty": 0}, 95, T)
    assert ok["passed"]
    assert not balance.gate(T - timedelta(days=40), 25, {"wrong_empty": 0}, 95, T, household=0)["passed"]
    assert balance.signal(True, True, "away", 95, True)
    assert not balance.signal(False, True, "away", 95, True)  # option off by default
    assert not balance.signal(True, True, "away", 80, True)
    assert not balance.signal(True, False, "away", 99, True)
