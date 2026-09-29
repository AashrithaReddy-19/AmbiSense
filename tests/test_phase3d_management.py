"""Phase 3D backend: layout validation, management RBAC, settings, notifications,
collaboration notes, audio capabilities, trends coverage filter."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app import models
from backend.app.auth import hash_password
from backend.app.config import get_settings
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app

Base.metadata.create_all(engine)
settings = get_settings()
PASSWORD = "StrongPassword!123"


@pytest.fixture
def token_auth():
    previous = (settings.auth_enabled, settings.auth_mode, settings.auth_secret_key)
    settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = True, "TOKEN", "phase3d-test-secret-key-at-least-32-chars"
    yield
    settings.auth_enabled, settings.auth_mode, settings.auth_secret_key = previous


def _user(db, email, role):
    row = models.User(email=email, display_name=email.split("@")[0].title(), role=role, password_hash=hash_password(PASSWORD))
    db.add(row); db.flush()
    return row


def _headers(client, email):
    token = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _square(x, y, size=0.2):
    return [{"x": x, "y": y}, {"x": x + size, "y": y}, {"x": x + size, "y": y + size}, {"x": x, "y": y + size}]


def _region(key, polygon, region_type="SEAT"):
    return {"region_key": key, "name": key.title(), "region_type": region_type, "polygon": polygon}


# --- Layout validation --------------------------------------------------------------

def test_valid_layout_saves_with_version_and_overlap_warning():
    with SessionLocal() as db:
        room = models.Classroom(name="Layout valid room", total_students=10, total_seats=10)
        db.add(room); db.commit(); room_id = room.id
    payload = {"name": "Front", "regions": [_region("a", _square(0.1, 0.1)), _region("b", _square(0.2, 0.2)), _region("c", _square(0.6, 0.6))]}
    with TestClient(app) as client:
        response = client.post(f"/api/v1/classrooms/{room_id}/layouts", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["version"] == 1
        assert [w["region_keys"] for w in body["warnings"]] == [["a", "b"]]
        assert client.post(f"/api/v1/classrooms/{room_id}/layouts", json=payload).json()["version"] == 2


@pytest.mark.parametrize("polygon, code", [
    ([{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.5}, {"x": 0.5, "y": 0.1}, {"x": 0.1, "y": 0.5}], "SELF_INTERSECTING"),
    ([{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}, {"x": 0.3, "y": 0.3}], "DEGENERATE_POLYGON"),
    ([{"x": 0.1, "y": 0.1}, {"x": 0.1001, "y": 0.1}, {"x": 0.1, "y": 0.1001}], "DEGENERATE_POLYGON"),
])
def test_invalid_polygons_are_rejected_and_nothing_is_saved(polygon, code):
    with SessionLocal() as db:
        room = models.Classroom(name=f"Layout invalid {code}", total_students=10, total_seats=10)
        db.add(room); db.commit(); room_id = room.id
    with TestClient(app) as client:
        response = client.post(f"/api/v1/classrooms/{room_id}/layouts", json={"name": "Bad", "regions": [_region("bad", polygon)]})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_LAYOUT"
        assert response.json()["error"]["details"][0]["code"] == code
        assert client.get(f"/api/v1/classrooms/{room_id}/layouts").json() == []


def test_out_of_bounds_and_too_few_points_are_rejected():
    with TestClient(app) as client:
        outside = client.post("/api/v1/layouts/validate", json={"name": "x", "regions": [_region("o", _square(0.9, 0.9, 0.3))]})
        assert outside.status_code == 422  # coordinates are constrained to the 0..1 frame by the schema
        few = client.post("/api/v1/layouts/validate", json={"name": "x", "regions": [_region("f", [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}])]})
        assert few.status_code == 422


def test_duplicate_region_keys_and_dry_run_validation():
    with TestClient(app) as client:
        duplicate = client.post("/api/v1/layouts/validate", json={"name": "d", "regions": [_region("same", _square(0.1, 0.1)), _region("same", _square(0.5, 0.5))]}).json()
        assert duplicate["valid"] is False and duplicate["errors"][0]["code"] == "DUPLICATE_REGION_KEY"
        good = client.post("/api/v1/layouts/validate", json={"name": "g", "regions": [_region("one", _square(0.1, 0.1)), _region("two", _square(0.5, 0.5))]}).json()
        assert good == {"valid": True, "errors": [], "warnings": []}


def test_geometry_helpers_directly():
    from backend.app.services.layout_validation import is_self_intersecting, polygon_area, polygons_overlap

    square = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert polygon_area(square) == 1
    assert not is_self_intersecting(square)
    assert is_self_intersecting([(0, 0), (1, 1), (1, 0), (0, 1)])
    assert polygons_overlap(square, [(0.5, 0.5), (2, 0.5), (2, 2), (0.5, 2)])
    assert polygons_overlap(square, [(0.25, 0.25), (0.75, 0.25), (0.5, 0.75)])  # fully contained
    assert not polygons_overlap(square, [(2, 2), (3, 2), (3, 3)])


# --- Management RBAC ----------------------------------------------------------------

def test_user_management_is_administrator_only_and_paginated(token_auth):
    with SessionLocal() as db:
        admin = _user(db, "rbac-admin@test", "ADMINISTRATOR")
        instructor = _user(db, "rbac-instructor@test", "INSTRUCTOR")
        viewer = _user(db, "rbac-viewer@test", "VIEWER")
        for index in range(3): _user(db, f"rbac-extra{index}@test", "VIEWER")
        db.commit()
    with TestClient(app) as client:
        admin_headers, instructor_headers, viewer_headers = (_headers(client, e) for e in ("rbac-admin@test", "rbac-instructor@test", "rbac-viewer@test"))
        assert client.get("/api/v1/users", headers=instructor_headers).status_code == 403
        assert client.get("/api/v1/users", headers=viewer_headers).status_code == 403
        assert client.post("/api/v1/users", json={"email": "x@test", "display_name": "X", "role": "VIEWER", "password": PASSWORD}, headers=instructor_headers).status_code == 403
        page = client.get("/api/v1/users?q=rbac-&page_size=2&page=1", headers=admin_headers)
        assert page.status_code == 200 and len(page.json()) == 2 and int(page.headers["X-Total-Count"]) >= 6
        assert all(row["role"] == "VIEWER" for row in client.get("/api/v1/users?role=viewer&q=rbac-", headers=admin_headers).json())
        assert all("password" not in row and "password_hash" not in row for row in page.json())


def test_only_administrators_may_read_or_change_settings_and_diagnostics(token_auth):
    with SessionLocal() as db:
        _user(db, "settings-admin@test", "ADMINISTRATOR"); _user(db, "settings-instructor@test", "INSTRUCTOR"); db.commit()
    with TestClient(app) as client:
        admin_headers, instructor_headers = _headers(client, "settings-admin@test"), _headers(client, "settings-instructor@test")
        for path in ("/api/settings", "/api/v1/settings/catalog", "/api/v1/system/diagnostics", "/api/v1/retention/policy"):
            assert client.get(path, headers=instructor_headers).status_code == 403, path
            assert client.get(path, headers=admin_headers).status_code == 200, path
        assert client.post("/api/v1/system/jobs/recover?confirm=true", headers=instructor_headers).status_code == 403


def test_permissions_endpoint_explains_roles(token_auth):
    with SessionLocal() as db:
        _user(db, "perm-viewer@test", "VIEWER"); db.commit()
    with TestClient(app) as client:
        body = client.get("/api/v1/auth/permissions", headers=_headers(client, "perm-viewer@test")).json()
    assert body["you"]["role"] == "VIEWER" and "note:write" not in body["you"]["permissions"]
    assert {row["role"] for row in body["roles"]} == {"ADMINISTRATOR", "INSTRUCTOR", "REVIEWER", "VIEWER"}
    assert body["auth_enabled"] is True


def test_layout_creation_requires_layout_permission(token_auth):
    with SessionLocal() as db:
        _user(db, "layout-viewer@test", "VIEWER")
        room = models.Classroom(name="Layout rbac room", total_students=5, total_seats=5)
        db.add(room); db.commit(); room_id = room.id
    with TestClient(app) as client:
        response = client.post(f"/api/v1/classrooms/{room_id}/layouts", json={"name": "n", "regions": []}, headers=_headers(client, "layout-viewer@test"))
    assert response.status_code == 403


# --- Settings -----------------------------------------------------------------------

@pytest.fixture
def restore_settings():
    with TestClient(app) as client:
        original = client.get("/api/settings").json()
    yield original
    with TestClient(app) as client:
        client.put("/api/settings?confirm_risky=true", json=original)
    with SessionLocal() as db:
        db.query(models.AuditEntry).filter(models.AuditEntry.action == "SETTINGS_UPDATED").delete()
        db.commit()


def test_settings_catalog_lists_real_settings_groups_and_no_secrets():
    with TestClient(app) as client:
        response = client.get("/api/v1/settings/catalog")
    body = response.json()
    keys = {entry["key"] for entry in body["settings"]}
    assert body["groups"] == ["General", "Analytics", "Models", "Thresholds", "Privacy & Retention", "Reports", "Optional Audio", "Feature Flags", "System"]
    assert {"ear_threshold", "retention_days", "demo_mode", "max_upload_mb", "auth_enabled"} <= keys
    assert "auth_secret_key" not in keys and "redis_url" not in keys and "database_url" not in keys
    assert "auth_secret_key" not in response.text
    read_only = [entry for entry in body["settings"] if not entry["editable"]]
    assert read_only and all(entry["source"] == "environment" for entry in read_only)
    editable = {entry["key"]: entry for entry in body["settings"] if entry["editable"]}
    assert editable["ear_threshold"]["unit"] == "ratio" and editable["ear_threshold"]["risky"] is True
    assert editable["expected_students"]["min"] == 1 and editable["expected_students"]["max"] == 500
    assert body["audio"]["status"] in {"DISABLED", "NOT_CONFIGURED", "MODEL_UNAVAILABLE", "READY"}


def test_risky_setting_change_requires_confirmation_and_is_audited(restore_settings):
    original = restore_settings
    changed = {**original, "ear_threshold": round(original["ear_threshold"] + 0.01, 2)}
    with TestClient(app) as client:
        refused = client.put("/api/settings", json=changed)
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "RISKY_CHANGE_REQUIRES_CONFIRMATION"
        assert refused.json()["error"]["details"]["keys"] == ["ear_threshold"]
        assert client.get("/api/settings").json()["ear_threshold"] == original["ear_threshold"]  # nothing changed silently
        saved = client.put("/api/settings?confirm_risky=true", json=changed)
        assert saved.status_code == 200 and saved.json()["changes"]["ear_threshold"]["to"] == changed["ear_threshold"]
    with SessionLocal() as db:
        audit = db.scalar(select(models.AuditEntry).where(models.AuditEntry.action == "SETTINGS_UPDATED").order_by(models.AuditEntry.id.desc()))
        assert audit.details["changes"]["ear_threshold"]["from"] == original["ear_threshold"]


def test_non_risky_change_needs_no_confirmation_and_unchanged_save_is_a_noop(restore_settings):
    original = restore_settings
    with TestClient(app) as client:
        assert client.put("/api/settings", json=original).json()["changes"] == {}
        assert client.put("/api/settings", json={**original, "expected_students": original["expected_students"] + 1}).status_code == 200


@pytest.mark.parametrize("field, value", [("ear_threshold", 5), ("retention_days", 0), ("expected_students", 501), ("transcription_provider", "OPENAI")])
def test_out_of_range_settings_are_rejected(restore_settings, field, value):
    with TestClient(app) as client:
        response = client.put("/api/settings?confirm_risky=true", json={**restore_settings, field: value})
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_FAILED"


# --- Audio capabilities --------------------------------------------------------------

def test_audio_capabilities_are_truthful(monkeypatch):
    from backend.app.services import audio_capabilities as module

    monkeypatch.setattr(settings, "audio_analytics_enabled", False)
    with TestClient(app) as client:
        assert client.get("/api/v1/audio/capabilities").json()["status"] == "DISABLED"
        monkeypatch.setattr(settings, "audio_analytics_enabled", True)
        monkeypatch.setattr(module.shutil, "which", lambda name: None)
        assert client.get("/api/v1/audio/capabilities").json()["status"] == "MODEL_UNAVAILABLE"
        monkeypatch.setattr(module.shutil, "which", lambda name: "ffmpeg")
        monkeypatch.setattr(settings, "transcription_provider", "NONE")
        assert client.get("/api/v1/audio/capabilities").json()["status"] == "NOT_CONFIGURED"
        monkeypatch.setattr(settings, "transcription_provider", "FASTER_WHISPER")
        monkeypatch.setattr(module.importlib.util, "find_spec", lambda name: None)
        assert client.get("/api/v1/audio/capabilities").json()["status"] == "MODEL_UNAVAILABLE"
        monkeypatch.setattr(module.importlib.util, "find_spec", lambda name: object())
        ready = client.get("/api/v1/audio/capabilities").json()
        assert ready["status"] == "READY" and ready["transcription"]["model_available"] is True
        monkeypatch.setattr(settings, "diarization_provider", "LOCAL_ADAPTER")
        diarization = client.get("/api/v1/audio/capabilities").json()["diarization"]
        assert diarization["configured"] is True and diarization["model_available"] is False  # no bundled model
        assert client.get("/api/v1/audio/capabilities").json()["identity"] == "anonymous"


# --- Notifications -------------------------------------------------------------------

def _notification(db, key, category="POOR_CAMERA", session_id=None, **kwargs):
    row = models.Notification(user_id=None, session_id=session_id, category=category, title=f"title {key}", message="message", dedupe_key=key, **kwargs)
    db.add(row); db.flush()
    return row


def test_notifications_paginate_with_totals_severity_and_safe_links():
    with SessionLocal() as db:
        session = models.Session(name="Notification link target", status="COMPLETED")
        db.add(session); db.flush()
        session_id = session.id
        db.query(models.Notification).filter(models.Notification.user_id.is_(None)).delete()
        for index in range(5): _notification(db, f"page-{index}", session_id=session_id if index == 0 else None)
        _notification(db, "critical", "PROCESSING_FAILED", session_id=999999)  # dangling: must not produce a link
        db.commit()
    with TestClient(app) as client:
        first = client.get("/api/v1/notifications?page_size=4&page=1")
        assert len(first.json()) == 4 and first.headers["X-Total-Count"] == "6" and first.headers["X-Unread-Count"] == "6"
        second = client.get("/api/v1/notifications?page_size=4&page=2")
        assert len(second.json()) == 2
        everything = client.get("/api/v1/notifications?page_size=50").json()
        by_title = {row["title"]: row for row in everything}
        assert by_title["title page-0"]["link"] == f"/sessions/{session_id}"
        assert by_title["title critical"]["severity"] == "CRITICAL" and by_title["title critical"]["link"] is None
        assert by_title["title page-1"]["severity"] == "WARNING"
        assert [row["title"] for row in client.get("/api/v1/notifications?severity=critical").json()] == ["title critical"]


def test_bulk_read_dismiss_and_unread_counts_are_persistent():
    with SessionLocal() as db:
        db.query(models.Notification).filter(models.Notification.user_id.is_(None)).delete()
        for index in range(3): _notification(db, f"bulk-{index}", "POOR_CAMERA" if index < 2 else "INSUFFICIENT_EVIDENCE")
        db.commit()
    with TestClient(app) as client:
        assert client.post("/api/v1/notifications/read-all?category=POOR_CAMERA").json() == {"updated": 2}
        listing = client.get("/api/v1/notifications")
        assert listing.headers["X-Unread-Count"] == "1"
        assert client.post("/api/v1/notifications/read-all").json() == {"updated": 1}
        assert client.post("/api/v1/notifications/read-all").json() == {"updated": 0}
        first = listing.json()[0]
        assert client.post(f"/api/v1/notifications/{first['id']}/dismiss").json()["dismissed"] is True
        assert len(client.get("/api/v1/notifications").json()) == 2
        assert len(client.get("/api/v1/notifications?include_dismissed=true").json()) == 3
        assert client.post("/api/v1/notifications/999999/read").status_code == 404


def test_notifications_are_scoped_to_their_owner(token_auth):
    with SessionLocal() as db:
        owner = _user(db, "notify-owner@test", "INSTRUCTOR"); _user(db, "notify-other@test", "INSTRUCTOR")
        row = models.Notification(user_id=owner.id, category="POOR_CAMERA", title="private", message="m", dedupe_key="scoped-1")
        db.add(row); db.commit(); notification_id = row.id
    with TestClient(app) as client:
        other = _headers(client, "notify-other@test")
        assert client.get("/api/v1/notifications", headers=other).json() == []
        assert client.post(f"/api/v1/notifications/{notification_id}/read", headers=other).status_code == 404
        assert client.post("/api/v1/notifications/read-all", headers=other).json() == {"updated": 0}


def test_notification_dedupe_key_is_unique_per_user():
    from sqlalchemy.exc import IntegrityError

    with SessionLocal() as db:
        user = _user(db, "dedupe-user@test", "VIEWER")
        db.add(models.Notification(user_id=user.id, category="POOR_CAMERA", title="a", message="m", dedupe_key="same-key")); db.commit()
        db.add(models.Notification(user_id=user.id, category="POOR_CAMERA", title="b", message="m", dedupe_key="same-key"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


# --- Collaboration notes -------------------------------------------------------------

def test_notes_show_author_role_edit_state_and_rbac(token_auth):
    with SessionLocal() as db:
        author = _user(db, "note-author@test", "INSTRUCTOR"); _user(db, "note-peer@test", "REVIEWER"); _user(db, "note-admin@test", "ADMINISTRATOR"); _user(db, "note-viewer@test", "VIEWER")
        session = models.Session(name="Notes RBAC session", status="COMPLETED")
        db.add(session); db.commit(); session_id = session.id
    with TestClient(app) as client:
        author_h, peer_h, admin_h, viewer_h = (_headers(client, e) for e in ("note-author@test", "note-peer@test", "note-admin@test", "note-viewer@test"))
        created = client.post("/api/v1/notes", json={"scope_type": "SESSION", "scope_id": session_id, "body": "First observation"}, headers=author_h)
        assert created.status_code == 200
        note = created.json()
        assert note["author"]["display_name"] == "Note-Author" and note["author"]["role"] == "INSTRUCTOR"
        assert note["edited"] is False and note["can_edit"] is True and note["version"] == 1
        assert client.post("/api/v1/notes", json={"scope_type": "SESSION", "scope_id": session_id, "body": "x"}, headers=viewer_h).status_code == 403
        as_peer = client.get(f"/api/v1/notes?scope_type=SESSION&scope_id={session_id}", headers=peer_h).json()[0]
        assert as_peer["can_edit"] is False
        as_viewer = client.get(f"/api/v1/notes?scope_type=SESSION&scope_id={session_id}", headers=viewer_h).json()[0]
        assert as_viewer["can_edit"] is False  # viewers can read but never edit
        forbidden = client.put(f"/api/v1/notes/{note['id']}", json={"body": "hijack", "review_status": "OPEN", "version": 1}, headers=peer_h)
        assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "NOTE_EDIT_FORBIDDEN"
        stale = client.put(f"/api/v1/notes/{note['id']}", json={"body": "late", "review_status": "OPEN", "version": 7}, headers=author_h)
        assert stale.status_code == 409
        updated = client.put(f"/api/v1/notes/{note['id']}", json={"body": "Revised", "review_status": "REVIEWED", "version": 1}, headers=author_h).json()
        assert updated["edited"] is True and updated["version"] == 2 and updated["body"] == "Revised"
        by_admin = client.put(f"/api/v1/notes/{note['id']}", json={"body": "Admin edit", "review_status": "RESOLVED", "version": 2}, headers=admin_h)
        assert by_admin.status_code == 200 and by_admin.json()["author"]["role"] == "INSTRUCTOR"  # authorship is preserved


def test_notes_are_denied_for_sessions_the_user_cannot_access(token_auth):
    with SessionLocal() as db:
        owner = _user(db, "note-room-owner@test", "INSTRUCTOR"); _user(db, "note-outsider@test", "INSTRUCTOR")
        room = models.Classroom(name="Private notes room", total_students=5, total_seats=5, owner_user_id=owner.id)
        db.add(room); db.flush()
        session = models.Session(name="Private notes session", status="COMPLETED", classroom_id=room.id)
        db.add(session); db.commit(); session_id = session.id
    with TestClient(app) as client:
        outsider = _headers(client, "note-outsider@test")
        assert client.get(f"/api/v1/notes?scope_type=SESSION&scope_id={session_id}", headers=outsider).status_code == 403
        assert client.post("/api/v1/notes", json={"scope_type": "SESSION", "scope_id": session_id, "body": "x"}, headers=outsider).status_code == 403


def test_notes_without_authentication_are_attributed_to_local_user():
    with SessionLocal() as db:
        session = models.Session(name="Local notes session", status="COMPLETED")
        db.add(session); db.commit(); session_id = session.id
    with TestClient(app) as client:
        note = client.post("/api/v1/notes", json={"scope_type": "SESSION", "scope_id": session_id, "body": "Local"}).json()
        assert note["author"]["display_name"] == "Local user" and note["can_edit"] is True


# --- Trends minimum coverage ----------------------------------------------------------

def test_trends_minimum_coverage_and_validation():
    with SessionLocal() as db:
        room = models.Classroom(name="Trend coverage room", total_students=10, total_seats=10)
        db.add(room); db.flush()
        session = models.Session(name="Trend coverage session", status="COMPLETED", classroom_id=room.id)
        db.add(session); db.flush()
        db.add(models.AnalyticsSnapshot(session_id=session.id, timestamp=0, student_count=4, occupied_seats=4))
        db.commit(); room_id = room.id
    with TestClient(app) as client:
        base = f"/api/v1/analytics/trends?classroom_id={room_id}&period=daily&metric=occupancy"
        unfiltered = client.get(base).json()
        assert unfiltered["points"] and unfiltered["filters_applied"]["minimum_coverage"] is None
        assert client.get(base + "&minimum_coverage=1.0").json()["excluded_by_filters"] >= 0
        impossible = client.get(base + "&minimum_coverage=0.0").json()
        assert len(impossible["points"]) == len(unfiltered["points"])
        for bad in ("1.5", "-0.1"):
            response = client.get(base + f"&minimum_coverage={bad}")
            assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_COVERAGE"
        assert client.get(base + "&confidence_min=2").json()["error"]["code"] == "INVALID_CONFIDENCE"


def test_trends_minimum_coverage_excludes_low_coverage_points():
    with SessionLocal() as db:
        room = models.Classroom(name="Trend coverage exclusion room", total_students=10, total_seats=10)
        db.add(room); db.flush()
        session = models.Session(name="Trend sparse session", status="COMPLETED", classroom_id=room.id)
        db.add(session); db.flush()
        db.add_all([models.AnalyticsSnapshot(session_id=session.id, timestamp=i, student_count=1 if i == 0 else 0) for i in range(4)])
        db.commit(); room_id = room.id
    with TestClient(app) as client:
        base = f"/api/v1/analytics/trends?classroom_id={room_id}&period=daily&metric=observable_participation"
        all_points = client.get(base).json()["points"]
        strict = client.get(base + "&minimum_coverage=0.99").json()
        assert strict["excluded_by_filters"] == len(all_points) - len(strict["points"])
        assert all(point["coverage"] is not None and point["coverage"] >= 0.99 for point in strict["points"])


# --- Reports data source --------------------------------------------------------------

def test_reports_support_test_data_source_and_reject_unknown():
    with SessionLocal() as db:
        db.add(models.Session(name="Reports test flagged", status="COMPLETED", is_test=True, analytics_mode="REAL"))
        db.add(models.Session(name="Reports real one", status="COMPLETED", is_test=False, analytics_mode="REAL"))
        db.commit()
    with TestClient(app) as client:
        names = lambda source: {row["name"] for row in client.get(f"/api/v1/reports?data_source={source}&page_size=100").json()["items"]}
        assert "Reports test flagged" in names("TEST") and "Reports real one" not in names("TEST")
        assert "Reports test flagged" not in names("REAL") and "Reports real one" in names("REAL")
        assert {"Reports test flagged", "Reports real one"} <= names("ALL")
        bad = client.get("/api/v1/reports?data_source=BOGUS")
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_DATA_SOURCE"
        assert client.get("/api/v1/reports?format=docx").json()["error"]["code"] == "INVALID_FORMAT"
