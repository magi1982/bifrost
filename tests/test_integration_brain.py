import json
import threading
import urllib.request

from demo import build


def test_demo_household_end_to_end(tmp_path):
    svc = build(str(tmp_path / "demo.db"))
    st = svc.status_view()
    assert st["guard"]["checks"] and st["ledger"]["people"]
    assert st["capability"]["doors_with_direction"] >= 2
    house = svc.house_view()
    assert house["entrances"] and house["map"]["links"]
    rec = svc.recognition_view()["items"]
    types = {i["type"] for i in rec}
    assert {"block", "person", "routine"} <= types
    person = next(i for i in rec if i["type"] == "person")
    assert person["steps"][0]["t"] == "or" and all("ref" in x for x in person["steps"][0]["items"])
    q = svc.questions_view()["items"]
    assert any(x["type"] == "suspicious_entry" for x in q)
    dev = svc.brain.inbox.deviations()
    assert {d["kind"] for d in dev} >= {"unexplained", "expected_missing"}
    pv = svc.people_view()
    assert len(pv["people"]) == 4 and all("0123456789abcdef" not in json.dumps(p) for p in pv["people"])
    bal = svc.balance_view()
    assert bal["kpis"]["wrong_empty"] == 1 and not bal["gate"]["passed"]
    pub = svc.client.published
    assert pub["binary_sensor.bifrost_suspicious_entry"][0] == "on"
    assert pub["binary_sensor.bifrost_empty_confirmed"][0] == "off"
    assert "sensor.bifrost_person_person_a" in pub
    # answering the suspicious entry with "that was us" clears it
    sid = next(x["id"] for x in q if x["type"] == "suspicious_entry")
    svc.answer(sid, "yes", "Person A")
    assert svc.brain.gs.suspicion is None


def test_http_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("BIFROST_DEV", "1")
    from bifrost_app.web import serve

    svc = build(str(tmp_path / "demo.db"))
    httpd = serve(svc, port=0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"

    def get(p):
        with urllib.request.urlopen(base + p) as r:  # noqa: S310
            return json.loads(r.read())

    def post(p, body):
        req = urllib.request.Request(base + p, json.dumps(body).encode(), {"Content-Type": "application/json", "X-Bifrost-Request": "1"})
        try:
            with urllib.request.urlopen(req) as r:  # noqa: S310
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        for p in ("/api/people", "/api/house", "/api/recognition", "/api/incidents", "/api/questions", "/api/balance", "/api/calendars"):
            assert isinstance(get(p), dict)
        code, r = post("/api/person", {"name": "Guest Example", "kind": "visitor"})
        assert code == 200 and r["id"] == "guest_example"
        code, r = post("/api/person", {"name": "<x>"})
        assert code == 400
        code, r = post("/api/correct", {"actual": "maybe"})
        assert code == 400
        code, r = post("/api/answer", {"id": "nope", "answer": "yes"})
        assert code == 400
        code, r = post("/api/floorplan", {"image": "PHN2Zz4="})  # <svg> is refused
        assert code == 400
        code, r = post("/api/person/delete", {"id": "guest_example"})
        assert code == 200 and r["deleted"]
    finally:
        httpd.shutdown()
