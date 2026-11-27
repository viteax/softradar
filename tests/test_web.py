import os

os.environ["AUTORUN"] = "0"
os.environ.setdefault("DATA_DIR", "/tmp/softradar-test")

from starlette.testclient import TestClient  # noqa: E402

from app.web import app  # noqa: E402

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.text == "ok"


def test_pages():
    for path in ("/", "/about", "/api/tenders", "/api/status"):
        assert client.get(path).status_code == 200, path


def test_report_xlsx():
    r = client.get("/report.xlsx")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
