import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

from sim import household

from bifrost_app.store import Store

spec = importlib.util.spec_from_file_location("backtest", Path(__file__).parents[1] / "tools" / "backtest.py")
backtest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backtest)


def test_backtest_finds_the_wrong_empty_of_the_simulated_child(tmp_path):
    s = household(14, trouble=True)
    db = str(tmp_path / "b.db")
    st = Store(db, retention_days=3650)
    for e in s.events:
        cat = "motion" if "motion" in e["entity_id"] else "openings" if "door" in e["entity_id"] else "devices"
        st.add_event(datetime.fromisoformat(e["ts"]), e["entity_id"], e["entity_id"], cat, "Evidence", e["state"], kind=e["kind"])
    for d in s.decisions:
        st.add_decision(datetime.fromisoformat(d["ts"]), d["state"], 95, [])
    st.put_obj("model", "house", {"sides": __import__("sim").SIDES})
    st.close()
    r = backtest.run(db, 60, now=s.t + timedelta(hours=1))
    assert r["wrong_empty"] == 2 and r["departures"] >= 12  # the two child days are not departures
    assert r["empty_time_recognised"] > 0.8
