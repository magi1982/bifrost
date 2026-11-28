from datetime import UTC, datetime, timedelta

from bifrost_app import everyday as ed

AREA = {"sensor.coffee": "Kitchen", "light.kitchen": "Kitchen", "binary_sensor.bath": "Bathroom", "binary_sensor.hall": "Hall", "light.hall": "Hall",
        "switch.pool_pump": "Garden", "binary_sensor.entrance": "Entrance", "binary_sensor.office": "Office", "switch.dishwasher": "Kitchen"}  # fmt: skip
START = datetime(2026, 10, 5, tzinfo=UTC).astimezone().replace(hour=0, minute=0)  # a Monday, local midnight


def ev(t, eid, kind="on", cat="manual"):
    return {"ts": t.astimezone(UTC).isoformat(), "entity_id": eid, "name": eid, "category": cat, "role": "Evidence", "state": "on", "kind": kind}


def month():
    out = []
    for d in range(28):
        day = START + timedelta(days=d)
        j = (d * 7) % 11  # a few minutes of daily jitter
        # morning chain: hall motion (+ automatic hall light 1 s later), coffee, kitchen light, bathroom
        t = day.replace(hour=6, minute=40) + timedelta(minutes=j)
        out += [ev(t, "binary_sensor.hall", cat="motion"), ev(t + timedelta(seconds=1), "light.hall", kind="on"), ev(t + timedelta(minutes=2), "sensor.coffee", kind="event", cat="energy"),
                ev(t + timedelta(minutes=3), "light.kitchen"), ev(t + timedelta(minutes=6), "binary_sensor.bath", cat="motion")]  # fmt: skip
        # pool pump, a timer to the minute
        out.append(ev(day.replace(hour=10, minute=0), "switch.pool_pump", kind="auto"))
        # dishwasher ~45 min after the kitchen light in the evening
        k = day.replace(hour=18, minute=30) + timedelta(minutes=j)
        out += [ev(k, "light.kitchen"), ev(k + timedelta(minutes=45), "switch.dishwasher")]
        # home office on weekdays: office active 08–12
        if day.weekday() < 5:
            for h in range(8, 12):
                out += [ev(day.replace(hour=h, minute=5), "binary_sensor.office", cat="motion"), ev(day.replace(hour=h, minute=35), "binary_sensor.office", cat="motion")]
        # cleaner on Tuesdays 09–12 at the entrance
        if day.weekday() == 1:
            for h in range(9, 12):
                out += [ev(day.replace(hour=h, minute=10), "binary_sensor.entrance", cat="motion"), ev(day.replace(hour=h, minute=40), "binary_sensor.entrance", cat="motion")]
    return out


def test_mine_finds_all_kinds():
    m = ed.mine(month(), AREA, START + timedelta(days=28))
    kinds = {p["kind"] for p in m["patterns"]}
    assert {"sequence", "phase", "weekly", "machine", "coupling"} <= kinds
    seq = max((p for p in m["patterns"] if p["kind"] == "sequence"), key=lambda p: len(p["steps"]))
    assert "light.hall" not in seq["steps"]  # the automatic light is merged into the motion that switches it
    assert seq["steps"][:2] == ["binary_sensor.hall", "sensor.coffee"] and seq["days"] >= 20
    assert any(p["kind"] == "machine" and p["entity_id"] == "switch.pool_pump" for p in m["patterns"])
    assert not any(p["kind"] == "machine" and p["entity_id"] == "binary_sensor.hall" for p in m["patterns"])
    co = [p for p in m["patterns"] if p["kind"] == "coupling" and p["b"] == "switch.dishwasher"]
    assert co and abs(co[0]["delay"] - 45) <= 5
    assert any(p["kind"] == "phase" and p["area"] == "Office" and p["group"] == "weekdays" and p["from"] == 8 for p in m["patterns"])
    assert any(p["kind"] == "weekly" and p["area"] == "Entrance" and p["group"] == "1" for p in m["patterns"])
    ids = [p["id"] for p in m["patterns"]]
    assert len(ids) == len(set(ids)) and ed.mine(month(), AREA, START)["patterns"][0]["id"] in ids  # stable ids


def test_closed_patterns_only():
    m = ed.mine(month(), AREA, START + timedelta(days=28))
    seqs = [tuple(p["steps"]) for p in m["patterns"] if p["kind"] == "sequence"]
    for g in seqs:
        assert not any(len(h) > len(g) and any(h[i : i + len(g)] == g for i in range(len(h) - len(g) + 1)) for h in seqs)


def test_breaks_missing_phase_and_long_on():
    m = ed.mine(month(), AREA, START + timedelta(days=28))
    monday = START + timedelta(days=28)  # next Monday, nothing happened in the office
    now = monday.replace(hour=14)
    states = {"light.kitchen": {"state": "on", "last_changed": (now - timedelta(hours=5)).isoformat()}}
    m["durations"] = {"light.kitchen": 20.0}
    b = ed.breaks(m, [], states, AREA, now)
    assert any(x["kind"] == "missing" and x["area"] == "Office" for x in b)
    assert any(x["kind"] == "long_on" and x["entity_id"] == "light.kitchen" for x in b)


def test_empty_and_service(tmp_path):
    assert ed.mine([], {}, datetime.now(UTC))["patterns"] == []
    import pytest
    from demo import build

    svc = build(str(tmp_path / "h.db"))
    svc.learn_job(datetime.now(UTC))
    v = svc.everyday_view()
    assert v["patterns"] and "breaks" in v
    pid = v["patterns"][0]["id"]
    svc.set_everyday({"id": pid, "name": "Morgen", "hidden": True})
    p = next(x for x in svc.everyday_view()["patterns"] if x["id"] == pid)
    assert p["name"] == "Morgen" and p["hidden"]
    for bad in ({"id": "x"}, {"id": pid, "name": "a" * 61}, {"id": pid, "hidden": "yes"}, []):
        with pytest.raises(ValueError):
            svc.set_everyday(bad)


def test_random_noise_gives_no_patterns():
    import random

    rnd = random.Random(1)
    ents = [f"binary_sensor.m{i}" for i in range(30)] + [f"light.l{i}" for i in range(30)]
    area = {e: f"A{i % 10}" for i, e in enumerate(ents)}
    evs = []
    for _ in range(40000):
        e = rnd.choice(ents)
        evs.append(ev(START + timedelta(seconds=rnd.randint(0, 28 * 86400)), e, kind=rnd.choice(["on", "on", "off"]), cat="motion" if "binary" in e else "manual"))
    assert ed.mine(evs, area, START + timedelta(days=28))["patterns"] == []
