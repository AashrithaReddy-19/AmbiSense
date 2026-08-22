import cv2
import numpy as np
from fastapi.testclient import TestClient

from backend.app.main import app, settings


def test_upload_processing_reports_and_search(tmp_path):
    previous_mode = settings.demo_mode
    settings.demo_mode = True
    video = tmp_path / "classroom.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 5, (160, 90))
    for index in range(15):
        frame = np.full((90, 160, 3), 20 + index * 3, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    with TestClient(app) as client, video.open("rb") as stream:
        uploaded = client.post("/api/videos/upload", files={"file": ("classroom.avi", stream, "video/x-msvideo")}, data={"name": "Acceptance session"})
        assert uploaded.status_code == 200
        session_id = uploaded.json()["id"]
        session = client.get(f"/api/sessions/{session_id}").json()
        assert session["status"] == "COMPLETED"
        assert session["progress"] == 100
        timeline = client.get(f"/api/sessions/{session_id}/timeline").json()
        assert len(timeline) >= 6
        assert all(point["mode"] == "DEMO" for point in timeline)
        assert client.get(f"/api/sessions/{session_id}/report?format=csv").headers["content-type"].startswith("text/csv")
        assert client.get(f"/api/sessions/{session_id}/report?format=pdf").headers["content-type"] == "application/pdf"
        search = client.post("/api/search", json={"query": "engagement below 90"}).json()
        assert search["matches"]
    settings.demo_mode = previous_mode
