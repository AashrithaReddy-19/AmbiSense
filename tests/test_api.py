from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_and_empty_dashboard():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert client.get("/api/dashboard/summary").status_code == 200


def test_session_lifecycle_and_search():
    with TestClient(app) as client:
        created = client.post("/api/sessions/start", json={"name": "API test"})
        assert created.status_code == 200
        session_id = created.json()["id"]
        assert client.get(f"/api/sessions/{session_id}").status_code == 200
        assert client.post(f"/api/sessions/{session_id}/stop").json()["status"] == "COMPLETED"
        assert client.post("/api/search", json={"query": "engagement below 50"}).status_code == 200
