"""End-to-end integration flows on isolated data (temporary database and artifact folders from conftest).

    upload -> job -> state transitions -> processing -> analytics -> report -> download
    two sessions -> comparison -> notices -> event frequencies -> CSV parity and formula safety
    search -> applied filters -> RBAC -> bounded results -> session action
    archive -> restore -> delete -> dependent rows and managed files removed -> audit -> no new FK violations
    live WebSocket with a mocked camera frame -> canonical metrics -> STOP -> reports

No historical or real session is read or changed.
"""
import csv
import io
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text

from backend.app import models
from backend.app.auth import hash_password
from backend.app.config import get_settings
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app, settings as main_settings
from backend.app.schemas import MetricAvailability

Base.metadata.create_all(engine)


def _video_bytes(tmp_path, name="clip.avi"):
    path = tmp_path / name
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5, (160, 90))
    for index in range(15):
        writer.write(np.full((90, 160, 3), 20 + index * 3, dtype=np.uint8))
    writer.release()
    return path.read_bytes()


def _fk_violations():
    with engine.connect() as connection:
        return len(connection.execute(text("PRAGMA foreign_key_check")).fetchall())


@pytest.fixture
def demo_mode():
    previous = main_settings.demo_mode
    main_settings.demo_mode = True  # deterministic synthetic analytics, clearly labelled DEMO; no camera or GPU needed
    yield
    main_settings.demo_mode = previous


def _upload(client, tmp_path, name, context, filename="clip.avi"):
    response = client.post("/api/uploads", files={"file": (filename, io.BytesIO(_video_bytes(tmp_path, filename)), "video/x-msvideo")}, data={"name": name, "activity_context": context})
    assert response.status_code == 200, response.text
    return response.json()


def test_full_workflow_upload_compare_search_archive_delete(tmp_path, demo_mode):
    transitions: list[str] = []

    def record(_target, value, _old, _initiator):
        transitions.append(value)

    with TestClient(app) as client:
        violations_before = _fk_violations()

        # ---- upload -> job -> state transitions -> processing -------------------------------------------------
        event.listen(models.Session.status, "set", record)
        try:
            first = _upload(client, tmp_path, "E2E lecture A", "LECTURE", "a.avi")
        finally:
            event.remove(models.Session.status, "set", record)
        assert first["status"] == "QUEUED" and first["job_id"] and first["source_filename"] == "a.avi" and first["activity_context"] == "LECTURE"
        expected_order = ["DECODING", "PROCESSING", "AGGREGATING", "GENERATING_REPORT", "COMPLETED"]
        positions = [transitions.index(state) for state in expected_order]
        assert positions == sorted(positions), transitions  # states advanced in the documented order
        job = client.get(f"/api/jobs/{first['job_id']}").json()
        assert job["status"] == "COMPLETED" and job["stage"] == "COMPLETED" and job["progress"] == 100 and job["report_ready"] is True

        # ---- analytics stored, report generated and downloadable -------------------------------------------------
        session_a = first["id"]
        timeline = client.get(f"/api/sessions/{session_a}/timeline").json()
        assert len(timeline) >= 5 and all(point["mode"] == "DEMO" for point in timeline)
        summary = client.get(f"/api/sessions/{session_a}/analytics").json()
        for contract in summary["metric_results"].values():
            MetricAvailability(**contract)
        artifacts = client.get(f"/api/v1/sessions/{session_a}/artifacts").json()["artifacts"]
        kinds = {item["kind"] for item in artifacts}
        assert {"source_video", "report_pdf", "report_csv", "report_metrics"} <= kinds
        report_paths = [next(item for item in artifacts if item["kind"] == kind) for kind in ("report_pdf", "report_csv", "report_metrics")]
        pdf = client.get(f"/api/sessions/{session_a}/report?format=pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
        metrics_csv = client.get(f"/api/sessions/{session_a}/report?format=metrics")
        assert metrics_csv.text.splitlines()[0].startswith("metric_name,value,available,reason")
        assert client.get(f"/api/sessions/{session_a}/report?format=csv").text.startswith("timestamp,")
        with SessionLocal() as db:  # downloading twice never duplicates report rows
            assert sorted(db.scalars(select(models.Report.format).where(models.Report.session_id == session_a)).all()) == ["csv", "metrics", "pdf"]

        # ---- two completed sessions -> comparison -> notices -> event frequencies -> CSV -----------------------------
        second = _upload(client, tmp_path, "=E2E exam B", "EXAMINATION", "b.avi")  # a leading "=" must be neutralised in the CSV export
        session_b = second["id"]
        with SessionLocal() as db:
            db.add_all([
                models.Event(session_id=session_a, timestamp=1, event_type="HAND_RAISED", severity="INFO", message="hand"),
                models.Event(session_id=session_a, timestamp=2, event_type="HAND_RAISED", severity="INFO", message="hand"),
                models.Event(session_id=session_a, timestamp=3, event_type="YAWNING", severity="INFO", message="yawn", review_state="EXCLUDED"),
                models.Event(session_id=session_b, timestamp=1, event_type="HAND_RAISED", severity="INFO", message="hand"),
            ])
            db.commit()
        compared = client.post("/api/v1/analytics/compare", json={"session_ids": [session_a, session_b], "metrics": ["occupancy", "observable_participation", "frame_quality"]})
        assert compared.status_code == 200, compared.text
        body = compared.json()
        codes = {notice["code"] for notice in body["compatibility"]["notices"]}
        assert "DIFFERENT_ACTIVITY_CONTEXTS" in codes and body["compatibility"]["compatible"] is False
        counts = {row["session_id"]: row["event_counts"] for row in body["sessions"]}
        assert counts[session_a] == {"HAND_RAISED": 2} and counts[session_b] == {"HAND_RAISED": 1}  # the excluded YAWNING event is not counted
        export = client.get(f"/api/v1/analytics/compare/export?session_ids={session_a},{session_b}&metrics=occupancy,observable_participation,frame_quality")
        assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
        rows = list(csv.DictReader(io.StringIO(export.text)))
        assert len(rows) == 2 * 3
        for row in rows:  # the CSV carries exactly the numbers the API returned
            contract = body["metric_results"][row["metric_name"]][row["session_id"]]
            assert (row["value"] == "") == (contract["value"] is None) and row["available"] == str(contract["available"])
            if contract["value"] is not None:
                assert float(row["value"]) == pytest.approx(contract["value"])
        assert {row["session_name"] for row in rows} == {"E2E lecture A", "'=E2E exam B"}  # formula injection neutralised

        # ---- search -> applied filters -> bounded results -> session action ------------------------------------------
        found = client.post("/api/search", json={"query": "Show completed lecture sessions", "data_source": "ALL"}).json()
        assert {"status", "activity_context", "data_source", "access"} <= {item["name"] for item in found["applied_filters"]}
        assert found["bounded"]["limit"] == 100 and len(found["matches"]) <= 100
        match = next(item for item in found["matches"] if item["session_id"] == session_a)
        assert match["status"] == "COMPLETED" and session_b not in {item["session_id"] for item in found["matches"]}  # B is an examination
        assert client.get(f"/api/sessions/{match['session_id']}").status_code == 200  # the "open session" target resolves

        # ---- archive -> restore -> delete -> cleanup ------------------------------------------------------------------
        with SessionLocal() as db:
            db.add(models.Notification(user_id=None, session_id=session_a, category="POOR_CAMERA", title="e2e", message="m", dedupe_key="e2e-key"))
            db.add(models.CollaborationNote(scope_type="SESSION", scope_id=session_a, body="e2e note"))
            db.commit()
        assert all(item["size_bytes"] > 0 for item in report_paths)
        assert client.post(f"/api/v1/sessions/{session_a}/archive").json()["archived"] is True
        assert session_a not in {row["id"] for row in client.get("/api/v1/sessions?include_tests=true&page_size=100").json()["items"]}
        assert client.post(f"/api/v1/sessions/{session_a}/archive?archived=false").json()["archived"] is False
        assert client.delete(f"/api/sessions/{session_a}").json()["error"]["code"] == "CONFIRMATION_REQUIRED"
        with SessionLocal() as db:
            paths = [row.path for row in db.scalars(select(models.Report).where(models.Report.session_id == session_a)).all()] + [db.get(models.Session, session_a).video_path]
        assert all(Path(path).exists() for path in paths)
        deleted = client.delete(f"/api/sessions/{session_a}?confirm=true").json()
        assert deleted["status"] == "deleted" and deleted["artifacts"]["failed"] == 0
        assert not any(Path(path).exists() for path in paths)  # managed files are gone
        with SessionLocal() as db:
            assert db.get(models.Session, session_a) is None
            for model in (models.AnalyticsSnapshot, models.Report, models.Event, models.Notification):
                assert db.scalar(select(func.count()).select_from(model).where(model.session_id == session_a)) == 0
            assert db.scalar(select(func.count()).select_from(models.CollaborationNote).where(models.CollaborationNote.scope_id == session_a, models.CollaborationNote.scope_type == "SESSION")) == 0
            assert db.scalar(select(models.AuditEntry.id).where(models.AuditEntry.action == "SESSION_DELETED", models.AuditEntry.resource_id == session_a))
            assert db.get(models.Session, session_b) is not None  # the other session is untouched
        assert _fk_violations() == violations_before  # deletion introduced no dangling references


def test_search_respects_rbac_and_data_source_on_isolated_sessions(demo_mode):
    settings = get_settings()
    previous = (settings.auth_enabled, settings.auth_mode, settings.auth_secret_key)
    settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = True, "TOKEN", "e2e-search-secret-key-at-least-32-chars"
    try:
        with SessionLocal() as db:
            owner = models.User(email="e2e-owner@test", display_name="Owner", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
            other = models.User(email="e2e-other@test", display_name="Other", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
            db.add_all([owner, other]); db.flush()
            room = models.Classroom(name="E2E private room", total_students=5, total_seats=5, owner_user_id=owner.id)
            db.add(room); db.flush()
            db.add_all([models.Session(name="E2E private completed", status="COMPLETED", classroom_id=room.id), models.Session(name="E2E shared completed", status="COMPLETED"), models.Session(name="E2E test completed", status="COMPLETED", is_test=True)])
            db.commit()
        with TestClient(app) as client:
            def names(email, source):
                token = client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPassword!123"}).json()["access_token"]
                body = client.post("/api/search", json={"query": "completed sessions", "data_source": source}, headers={"Authorization": f"Bearer {token}"}).json()
                assert len(body["matches"]) <= 100
                return {match["session"] for match in body["matches"]}

            owner_real, other_real = names("e2e-owner@test", "REAL"), names("e2e-other@test", "REAL")
            assert "E2E private completed" in owner_real and "E2E private completed" not in other_real  # RBAC applies to every match
            assert "E2E shared completed" in owner_real and "E2E shared completed" in other_real
            assert "E2E test completed" not in owner_real | other_real  # REAL never includes test-flagged sessions
            assert "E2E test completed" in names("e2e-other@test", "TEST")
    finally:
        settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = previous


def test_live_websocket_with_a_mocked_camera_frame_reports_canonical_metrics_and_reports():
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"name": "E2E live session", "source_type": "LIVE", "is_test": True}).json()
        ok, jpeg = cv2.imencode(".jpg", np.full((240, 320, 3), 90, dtype=np.uint8))
        assert ok
        with client.websocket_connect(f"/ws/live/{session['id']}") as socket:
            assert socket.receive_json()["type"] == "status"
            socket.send_text("PING")
            assert socket.receive_json()["type"] == "pong"
            socket.send_bytes(jpeg.tobytes())
            update = socket.receive_json()
            assert update["type"] == "live_metrics" and update["sequence"] == 1
            for name in ("occupancy", "frame_quality", "unoccupied_capacity"):
                MetricAvailability(**update["metrics"][name])
            assert update["pipeline"]["backend_receiving"] is True and update["privacy_mode"] is True
            assert set(update["metrics"]["occupancy"]) == {"value", "available", "reason", "coverage", "confidence", "valid_observations", "total_observations"}
            socket.send_text("STOP")
        final = client.get(f"/api/sessions/{session['id']}").json()
        assert final["status"] == "COMPLETED"
        reports = client.get("/api/v1/reports?data_source=TEST&page_size=100").json()["items"]
        row = next(item for item in reports if item["session_id"] == session["id"])
        assert row["available_formats"] == ["csv", "metrics", "pdf"]
