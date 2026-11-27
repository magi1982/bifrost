import json
import threading
import urllib.error
import urllib.request

import pytest

from bifrost_app.ha_client import encode_frame
from bifrost_app.web import MAX_BODY, BoundedThreadingHTTPServer, ThreadingHTTPServer, make_handler, validate_entity_update


def test_validate_ok():
    assert validate_entity_update({"entity_id": "light.kitchen", "status": "included", "category": "manual", "role": "Evidence"}) == ("light.kitchen", "included", "manual", "Evidence")


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"entity_id": "../etc/passwd", "status": "included"},
        {"entity_id": "Light.X", "status": "included"},
        {"entity_id": "light.x", "status": "root"},
        {"entity_id": "light.x", "status": "included", "category": 5},
        {"entity_id": "light.x", "status": "included", "role": "<script>"},
        {"entity_id": "light." + "a" * 300, "status": "included"},
    ],
)
def test_validate_rejects(body):
    with pytest.raises(ValueError):
        validate_entity_update(body)


class FakeService:
    def __init__(self):
        self.scans = 0

    def status_view(self):
        return {"ok": True}

    def entities_view(self):
        return {"entities": []}

    def request_scan(self):
        self.scans += 1

    def update_entity(self, eid, status, cat, role):
        if eid == "light.missing":
            raise KeyError(eid)
        return {"entity_id": eid, "status": status}


def _server(dev):
    svc = FakeService()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc, dev))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, svc, f"http://127.0.0.1:{httpd.server_address[1]}"


def _req(url, body=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hdr = {"Content-Type": "application/json", "X-Bifrost-Request": "1"} if headers is None else headers
    req = urllib.request.Request(url, data=data, headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310
            return r.status, json.loads(r.read() or b"null"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null"), e.headers


def test_only_ingress_allowed():
    httpd, _, base = _server(dev=False)
    try:
        assert _req(base + "/api/status")[0] == 403
    finally:
        httpd.shutdown()


def test_api_in_dev_mode():
    httpd, svc, base = _server(dev=True)
    try:
        code, body, headers = _req(base + "/api/status")
        assert code == 200 and body == {"ok": True}
        assert headers["X-Content-Type-Options"] == "nosniff" and "frame-ancestors" in headers["Content-Security-Policy"]
        assert _req(base + "/api/scan", {})[0] == 202 and svc.scans == 1
        assert _req(base + "/api/entity", {"entity_id": "light.a", "status": "included"})[0] == 200
        assert _req(base + "/api/entity", {"entity_id": "light.missing", "status": "included"})[0] == 404
        assert _req(base + "/api/entity", {"entity_id": "bad", "status": "included"})[0] == 400
        assert _req(base + "/api/entity", raw=b"{not json")[0] == 400
        assert _req(base + "/api/entity", raw=b"x" * (MAX_BODY + 1))[0] == 413
        assert _req(base + "/../../etc/passwd")[0] == 404
        assert _req(base + "/nope")[0] == 404
        # CSRF: a plain form post (no custom header / wrong content type) is refused
        assert _req(base + "/api/scan", raw=b"a=1", headers={"Content-Type": "application/x-www-form-urlencoded"})[0] == 403
        assert _req(base + "/api/scan", {}, headers={"Content-Type": "application/json"})[0] == 403
        assert svc.scans == 1
        # a browser marks requests from another site – refused even with the custom header
        assert _req(base + "/api/scan", {}, headers={"Content-Type": "application/json", "X-Bifrost-Request": "1", "Sec-Fetch-Site": "cross-site"})[0] == 403
        assert _req(base + "/api/scan", {}, headers={"Content-Type": "application/json", "X-Bifrost-Request": "1", "Sec-Fetch-Site": "same-origin"})[0] == 202
    finally:
        httpd.shutdown()


def test_ws_frame_masked_and_lengths():
    small = encode_frame(b"hi")
    assert small[0] == 0x81 and small[1] & 0x80 and small[1] & 0x7F == 2
    mid = encode_frame(b"x" * 300)
    assert mid[1] & 0x7F == 126 and int.from_bytes(mid[2:4], "big") == 300
    big = encode_frame(b"x" * 70000)
    assert big[1] & 0x7F == 127 and int.from_bytes(big[2:10], "big") == 70000


def test_bounded_server_rejects_when_full():
    import socket

    svc = FakeService()
    BoundedThreadingHTTPServer.max_threads = 1
    httpd = BoundedThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc, True))
    BoundedThreadingHTTPServer.max_threads = 16
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        hog = socket.create_connection(("127.0.0.1", port))  # holds the only slot (no request sent)
        import time

        time.sleep(0.3)
        code = _req(f"http://127.0.0.1:{port}/api/status")[0]
        assert code == 503
        hog.close()
    finally:
        httpd.shutdown()


def test_token_fallback_from_s6_env(tmp_path, monkeypatch):
    from bifrost_app import ha_client

    (tmp_path / "SUPERVISOR_TOKEN").write_text("abc\n")
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("HA_TOKEN", raising=False)
    monkeypatch.setattr(ha_client, "S6_ENV_DIR", str(tmp_path))
    c = ha_client.HAClient()
    assert c.base_url == "http://supervisor/core"


def test_missing_token_raises(tmp_path, monkeypatch):
    from bifrost_app import ha_client

    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("HA_TOKEN", raising=False)
    monkeypatch.setattr(ha_client, "S6_ENV_DIR", str(tmp_path))
    with pytest.raises(ha_client.HAError):
        ha_client.HAClient()


def test_chunked_body_like_ha_ingress():
    import http.client

    httpd, svc, base = _server(dev=True)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        body = json.dumps({"entity_id": "light.a", "status": "ignored"}).encode()
        conn.putrequest("POST", "/api/entity")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("X-Bifrost-Request", "1")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        for part in (body[:10], body[10:]):
            conn.send(f"{len(part):x}\r\n".encode() + part + b"\r\n")
        conn.send(b"0\r\n\r\n")
        r = conn.getresponse()
        assert r.status == 200 and json.loads(r.read())["status"] == "ignored"
        # oversized chunked body is refused
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        conn.putrequest("POST", "/api/entity")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("X-Bifrost-Request", "1")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        big = b"x" * (MAX_BODY + 10)
        conn.send(f"{len(big):x}\r\n".encode() + big + b"\r\n0\r\n\r\n")
        assert conn.getresponse().status == 413
    finally:
        httpd.shutdown()


@pytest.mark.parametrize("body", [{}, {"on": "yes"}, {"on": 1}, []])
def test_guest_validation(body):
    from bifrost_app.web import validate_guest

    with pytest.raises(ValueError):
        validate_guest(body)


def test_floorplan_query_is_validated():
    httpd, svc, base = _server(dev=True)
    try:
        code = _req(base + "/api/floorplan?floor=../../etc")[0]
        assert code == 400
        svc.brain = type("B", (), {"floorplan_bytes": staticmethod(lambda k: (b"\x89PNG\r\n\x1a\nxx", "image/png") if k == "eg" else None)})()
        with urllib.request.urlopen(base + "/api/floorplan?floor=eg&v=1", timeout=5) as r:  # noqa: S310
            assert r.headers["Cache-Control"].startswith("private, max-age=") and r.headers["Content-Type"] == "image/png"
        assert _req(base + "/api/status")[2]["Cache-Control"] == "no-store"
    finally:
        httpd.shutdown()
