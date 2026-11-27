from datetime import datetime, timedelta

from sim import META, SIDES, household

from bifrost_app import baseline
from bifrost_app.brain import Brain
from bifrost_app.store import Store


def test_rare_moments_and_heat():
    s = household(28)
    m = baseline.learn(s.events, META)
    assert m["weeks"] >= 4
    usual = next(datetime.fromisoformat(e["ts"]) for e in s.events if e["entity_id"] == "binary_sensor.garage_door")
    assert baseline.rarity(m, "binary_sensor.garage_door", usual) < 2
    night = usual.replace(hour=3)
    assert baseline.is_rare(m, "binary_sensor.garage_door", night) >= baseline.RARE_BITS
    assert baseline.is_rare(m, "binary_sensor.garage_door", usual) is None
    h = baseline.heat(m, "binary_sensor.garage_door")
    assert len(h) == 168 and max(h) > 0.3
    assert baseline.rarity(m, "binary_sensor.unknown", night) is None


def test_path_matrix_between_areas():
    s = household(7)
    meta = {k: {**v} for k, v in META.items()}
    p = baseline.paths(s.events, meta, SIDES)
    assert "Hallway" in p["areas"] and "Cloakroom" in p["areas"]
    i, j = p["areas"].index("Hallway"), p["areas"].index("Cloakroom")
    assert p["cells"][i][j]["n"] > 0 and p["cells"][i][j]["s"] <= 10


def test_live_rare_and_contradiction_deviations(tmp_path):
    s = household(28)
    b = Brain(Store(str(tmp_path / "s.db")), {})
    b.meta = META
    b.baseline = baseline.learn(s.events, META)
    b.detector.model = {"sides": SIDES}
    t = s.t.replace(hour=3, minute=12) + timedelta(days=1)
    b.on_edge({"ts": t, "entity_id": "binary_sensor.garage_door", "kind": "on", "state": "on"})
    kinds = [d["kind"] for d in b.inbox.deviations()]
    assert "rare" in kinds
    b.last_extra = {"state_before": "away"}
    b.on_edge({"ts": t + timedelta(hours=1), "entity_id": "binary_sensor.motion_living", "kind": "on", "state": "on"})
    assert "contradiction" in [d["kind"] for d in b.inbox.deviations()]
