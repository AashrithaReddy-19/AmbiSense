"""Query-count regression tests: list endpoints must not issue queries per row."""
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.app import crud, models
from backend.app.auth import Principal, bulk_accessible_sessions, can_access_session, hash_password
from backend.app.config import get_settings
from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app

Base.metadata.create_all(engine)
settings = get_settings()


@contextmanager
def count_queries():
    counter = {"n": 0}

    def before(*_args):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _seed_sessions(db, prefix, count, room_id=None):
    ids = []
    for index in range(count):
        session = models.Session(name=f"{prefix} {index}", status="COMPLETED", analytics_mode="REAL", classroom_id=room_id)
        db.add(session); db.flush()
        db.add(models.AnalyticsSnapshot(session_id=session.id, timestamp=0, student_count=3, occupied_seats=3))
        db.add(models.QualityAssessment(session_id=session.id, timestamp=0, overall_quality=80, status="GOOD", details={}))
        db.add(models.Event(session_id=session.id, timestamp=1, event_type="HAND_RAISED", severity="INFO", message="hand"))
        db.add(models.Report(session_id=session.id, format="pdf", path=f"{prefix}{index}.pdf"))
        ids.append(session.id)
    db.commit()
    return ids


def test_reports_query_count_does_not_grow_with_page_size():
    with SessionLocal() as db:
        room = models.Classroom(name="Query efficiency room", total_students=10, total_seats=10)
        db.add(room); db.flush(); room_id = room.id
        _seed_sessions(db, "Efficiency report", 12, room_id)
    counts = {}
    with TestClient(app) as client:
        for size in (2, 12):
            with count_queries() as counter:
                body = client.get(f"/api/v1/reports?classroom_id={room_id}&page_size={size}").json()
            assert len(body["items"]) == size
            counts[size] = counter["n"]
    assert counts[12] == counts[2], counts  # constant, not one-per-row


def test_batch_summaries_are_identical_to_single_summaries():
    with SessionLocal() as db:
        ids = _seed_sessions(db, "Batch parity", 3)
        db.add(models.AnalyticsSnapshot(session_id=ids[0], timestamp=5, student_count=0, occupied_seats=0))
        db.commit()
        sessions = [db.get(models.Session, i) for i in ids]
        batched = crud.batch_session_summaries(db, sessions)
        for session_id in ids:
            assert batched[session_id] == crud.session_summary(db, session_id)
        assert crud.batch_session_summaries(db, []) == {}


def test_sessions_list_uses_constant_queries_for_non_admin_users():
    with SessionLocal() as db:
        owner = models.User(email="qe-owner@test", display_name="Owner", role="INSTRUCTOR", password_hash=hash_password("StrongPassword!123"))
        db.add(owner); db.flush()
        rooms = []
        for index in range(6):
            room = models.Classroom(name=f"QE room {index}", total_students=5, total_seats=5, owner_user_id=owner.id if index % 2 == 0 else None)
            db.add(room); db.flush(); rooms.append(room.id)
        for room_id in rooms:
            _seed_sessions(db, f"QE session r{room_id}", 3, room_id)
        owner_id = owner.id
    user = Principal(owner_id, "INSTRUCTOR", "qe-owner@test")
    with SessionLocal() as db:
        candidates = db.query(models.Session).filter(models.Session.name.like("QE session%")).all()
        with count_queries() as counter:
            accessible = bulk_accessible_sessions(db, user, candidates)
        assert counter["n"] <= 4  # course membership, ownership, classroom owners, membership classrooms
        assert {s.id for s in accessible} == {s.id for s in candidates if can_access_session(db, user, s)}
        assert len(accessible) == len(candidates)


def test_bulk_access_matches_per_row_rules_for_every_role_combination():
    with SessionLocal() as db:
        owner = models.User(email="bulk-owner@test", display_name="Owner", role="INSTRUCTOR")
        member = models.User(email="bulk-member@test", display_name="Member", role="REVIEWER")
        outsider = models.User(email="bulk-outsider@test", display_name="Outsider", role="INSTRUCTOR")
        db.add_all([owner, member, outsider]); db.flush()
        private_room = models.Classroom(name="Bulk private", total_students=5, total_seats=5, owner_user_id=owner.id)
        open_room = models.Classroom(name="Bulk open", total_students=5, total_seats=5)
        db.add_all([private_room, open_room]); db.flush()
        course = models.Course(code="BULK1", name="Bulk course", classroom_id=private_room.id, owner_user_id=owner.id)
        db.add(course); db.flush()
        db.add(models.CourseMembership(course_id=course.id, user_id=member.id, membership_role="REVIEWER"))
        sessions = [
            models.Session(name="bulk private", classroom_id=private_room.id, status="COMPLETED"),
            models.Session(name="bulk open", classroom_id=open_room.id, status="COMPLETED"),
            models.Session(name="bulk none", status="COMPLETED"),
            models.Session(name="bulk via course", course_id=course.id, status="COMPLETED"),
            models.Session(name="bulk dangling", classroom_id=987654, status="COMPLETED"),
        ]
        db.add_all(sessions); db.commit()
        for account in (owner, member, outsider):
            user = Principal(account.id, account.role, account.email)
            expected = [s.id for s in sessions if can_access_session(db, user, s)]
            assert [s.id for s in bulk_accessible_sessions(db, user, sessions)] == expected, account.email
        admin = Principal(None, "ADMINISTRATOR", "admin")
        assert len(bulk_accessible_sessions(db, admin, sessions)) == len(sessions)


def test_trends_and_compare_query_counts_do_not_grow_with_sessions():
    with SessionLocal() as db:
        small_room, large_room = models.Classroom(name="Trend small room", total_students=5, total_seats=5), models.Classroom(name="Trend large room", total_students=5, total_seats=5)
        db.add_all([small_room, large_room]); db.flush()
        small_ids = _seed_sessions(db, "Trend small", 2, small_room.id)
        large_ids = _seed_sessions(db, "Trend large", 5, large_room.id)
        small_id, large_id = small_room.id, large_room.id
    counts = {}
    with TestClient(app) as client:
        for label, room_id in (("small", small_id), ("large", large_id)):
            with count_queries() as counter:
                assert client.get(f"/api/v1/analytics/trends?classroom_id={room_id}&period=session&metric=occupancy").status_code == 200
            counts[label] = counter["n"]
        assert counts["small"] == counts["large"], counts
        with count_queries() as two:
            assert client.post("/api/v1/analytics/compare", json={"session_ids": large_ids[:2], "metrics": ["occupancy"]}).status_code == 200
        with count_queries() as five:
            assert client.post("/api/v1/analytics/compare", json={"session_ids": large_ids, "metrics": ["occupancy"]}).status_code == 200
        assert two["n"] == five["n"], (two, five)
    assert small_ids
