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
        assert client.post(f"/api/sessions/{session_id}/stop").json()["status"] == "STOPPED"
        assert client.post("/api/search", json={"query": "engagement below 50"}).status_code == 200


def test_pipeline_health_quality_and_websocket_schema():
    with TestClient(app) as client:
        created = client.post("/api/sessions", json={"name": "WebSocket schema test", "source_type": "LIVE"}).json()
        session_id = created["id"]
        health = client.get("/api/v1/system/pipeline-health", params={"session_id": session_id}).json()
        assert health["backend_connection"] == "CONNECTED"
        quality = client.get(f"/api/v1/sessions/{session_id}/quality").json()
        assert quality["status"] == "UNAVAILABLE" and quality["overall_quality"] is None
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            message = socket.receive_json()
            assert message["type"] == "snapshot" and message["sequence"] == 1
            assert message["latency_ms"] is None and message["analytics"] is None
