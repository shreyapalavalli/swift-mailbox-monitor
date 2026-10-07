import json

import pytest
from fastapi.testclient import TestClient

from app.db.repository import SwiftRepository
from app.dependencies import get_processor, get_repository
from app.graph.auth_service import SignInRequiredError
from app.main import app

MX_REF = "swi04003-2026-09-08T06:43:03.23847.2373755Z"


class FakeProcessor:
    def __init__(self, exc=None):
        self.exc = exc
        self.is_running = False

    async def run_once(self):
        if self.exc:
            raise self.exc
        return {"processed": 3}


def _row(ref, status="ACTION_REQUIRED", **kw):
    row = {"reference": ref, "graph_message_id": "g-" + ref, "category": "OTHER",
           "status": status, "priority": "NORMAL", "matched_terms": json.dumps(["amend"])}
    row.update(kw)
    return row


@pytest.fixture
def repo(tmp_path):
    r = SwiftRepository(str(tmp_path / "api.db"))
    r.upsert_action(_row("R1"))
    r.upsert_action(_row("ALERT1", "PRIORITY", priority="HIGH", category="AMENDMENT"))
    r.upsert_action(_row(MX_REF))
    return r


@pytest.fixture
def proc():
    return FakeProcessor()


@pytest.fixture
def client(repo, proc):
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_processor] = lambda: proc
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_decodes_matched_terms(client):
    rows = client.get("/api/swifts").json()
    assert len(rows) == 3
    assert rows[0]["matched_terms"] == ["amend"]
    assert [r["reference"] for r in client.get("/api/swifts?status=PRIORITY").json()] == ["ALERT1"]


def test_alerts_only_priority(client):
    rows = client.get("/api/swifts/alerts").json()
    assert [r["reference"] for r in rows] == ["ALERT1"]
    assert client.get("/api/swifts/alerts?since=2999-01-01T00:00:00Z").json() == []


def test_since_and_limit_validation(client):
    assert client.get("/api/swifts?since=garbage").status_code == 422
    assert client.get("/api/swifts?limit=0").status_code == 422
    assert client.get("/api/swifts?limit=1001").status_code == 422
    assert client.get("/api/swifts?since=2000-01-01T00:00:00Z").status_code == 200
    assert len(client.get("/api/swifts?limit=1").json()) == 1


def test_metrics(client):
    body = client.get("/api/swifts/metrics").json()
    assert body["open_action_required"] == 2
    assert body["open_priority"] == 1


def test_get_and_404(client):
    assert client.get("/api/swifts/R1").json()["reference"] == "R1"
    assert client.get("/api/swifts/NOPE").status_code == 404


def test_patch_status_validates(client, repo):
    assert client.patch("/api/swifts/R1", json={"status": "BOGUS"}).status_code == 422
    assert client.patch("/api/swifts/R1", json={"status": "RESOLVED"}).json()["status"] == "RESOLVED"
    assert repo.get_action("R1")["status"] == "RESOLVED"
    assert client.patch("/api/swifts/NOPE", json={"status": "RESOLVED"}).status_code == 404


def test_get_mx_reference_with_colons(client):
    r = client.get(f"/api/swifts/{MX_REF}")
    assert r.status_code == 200
    assert r.json()["reference"] == MX_REF


def test_process_run_and_log(client, proc, repo):
    assert client.post("/api/process/run").json() == {"processed": 3}
    proc.exc = SignInRequiredError("Microsoft sign-in required. Visit /auth/login first.")
    r = client.post("/api/process/run")
    assert r.status_code == 401 and "sign-in" in r.json()["detail"]
    repo.record_processed({"graph_message_id": "m1", "is_swift": 0, "outcome": "SKIPPED"})
    assert len(client.get("/api/process/log?limit=5").json()) == 1
    assert client.get("/api/process/log?limit=0").status_code == 422


def test_process_run_unknown_runtime_error_is_500(repo, proc):
    proc.exc = RuntimeError("bug")
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_processor] = lambda: proc
    try:
        r = TestClient(app, raise_server_exceptions=False).post("/api/process/run")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 500


def test_process_run_conflict_while_running(client, proc):
    proc.is_running = True
    r = client.post("/api/process/run")
    assert r.status_code == 409
    assert r.json() == {"detail": "A processing run is already in progress."}


def test_cors_header_for_frontend(client):
    r = client.get("/api/swifts", headers={"Origin": "http://localhost:5000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5000"
