from starlette.testclient import TestClient

from app.web import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.text == "ok"


def test_index():
    r = client.get("/")
    assert r.status_code == 200
    assert "<h1>" in r.text
