from datetime import datetime
from fastapi.testclient import TestClient
from backend.app import models
from backend.app.config import get_settings
from backend.app.database import Base,SessionLocal,engine
from backend.app.main import app
from backend.app.metrics import metric_envelope

def test_rbac_authentication_permissions_and_classroom_isolation():
 Base.metadata.create_all(engine);settings=get_settings();old=settings.auth_enabled;old_mode=settings.auth_mode
 with SessionLocal() as db:
  admin=models.User(email="p4-admin@test",display_name="Admin",role="ADMINISTRATOR");instructor=models.User(email="p4-instructor@test",display_name="Instructor",role="INSTRUCTOR");viewer=models.User(email="p4-viewer@test",display_name="Viewer",role="VIEWER");db.add_all([admin,instructor,viewer]);db.commit();admin_id,instructor_id,viewer_id=admin.id,instructor.id,viewer.id
 settings.auth_enabled=True;settings.auth_mode="DEVELOPMENT"
 try:
  with TestClient(app) as client:
   assert client.get("/api/v1/courses").status_code==401
   assert client.post("/api/v1/users",headers={"X-User-Id":str(viewer_id)},json={"email":"blocked@test","display_name":"Blocked","role":"VIEWER","password":"StrongPassword!123"}).status_code==403
   created=client.post("/api/v1/classrooms",headers={"X-User-Id":str(instructor_id)},json={"name":"Private Lab","total_students":20,"total_seats":24});assert created.status_code==200
   room_id=created.json()["id"]
   assert all(row["id"]!=room_id for row in client.get("/api/v1/classrooms",headers={"X-User-Id":str(viewer_id)}).json())
   assert client.put(f"/api/v1/classrooms/{room_id}",headers={"X-User-Id":str(viewer_id)},json={"name":"No","total_students":1,"total_seats":1}).status_code==403
   assert client.post("/api/v1/users",headers={"X-User-Id":str(admin_id)},json={"email":"new@test","display_name":"New","role":"REVIEWER","password":"StrongPassword!123"}).status_code==200
 finally:settings.auth_enabled=old;settings.auth_mode=old_mode

def test_course_dashboard_comparison_trends_notifications_notes_and_report():
 settings=get_settings();old=settings.auth_enabled;settings.auth_enabled=False
 try:
  with SessionLocal() as db:
   room=models.Classroom(name="P4 aggregate room",total_students=30,total_seats=30);db.add(room);db.commit();course=models.Course(code="P4-101",name="Aggregate Analytics",classroom_id=room.id);db.add(course);db.commit()
   a=models.Session(name="P4 lecture",status="COMPLETED",classroom_id=room.id,course_id=course.id,activity_context="LECTURE");b=models.Session(name="P4 discussion",status="COMPLETED",classroom_id=room.id,course_id=course.id,activity_context="GROUP_DISCUSSION");db.add_all([a,b]);db.commit()
   db.add_all([models.AnalyticsSnapshot(session_id=a.id,timestamp=1,student_count=10,engagement_score=70,attention_score=75),models.AnalyticsSnapshot(session_id=b.id,timestamp=1,student_count=10,engagement_score=80,attention_score=60),models.QualityAssessment(session_id=a.id,timestamp=1,overall_quality=30,status="POOR",details={})]);db.commit();course_id,room_id,a_id,b_id=course.id,room.id,a.id,b.id
  with TestClient(app) as client:
   dashboard=client.get(f"/api/v1/courses/{course_id}/dashboard").json();assert dashboard["session_count"]==2 and dashboard["metrics"]["audio_quality"]["value"] is None
   classroom=client.get(f"/api/v1/classrooms/{room_id}/dashboard").json();assert classroom["metrics"]["observable_participation"]["value"]==75
   comparison=client.post("/api/v1/analytics/compare",json={"session_ids":[a_id,b_id],"metrics":["observable_participation","audio_quality"]}).json();assert comparison["compatible"] is False and "different activity contexts" in comparison["warnings"][0];assert comparison["compatibility"]["notices"][0]["code"]=="DIFFERENT_ACTIVITY_CONTEXTS"
   trends=client.get(f"/api/v1/analytics/trends?course_id={course_id}&period=weekly&data_source=ALL").json();assert {point["context"] for point in trends["points"]}=={"LECTURE","GROUP_DISCUSSION"}
   first=client.post("/api/v1/notifications/generate").json();second=client.post("/api/v1/notifications/generate").json();assert first["created"]>=1 and second["created"]==0
   notification=client.get("/api/v1/notifications").json()[0];assert client.post(f"/api/v1/notifications/{notification['id']}/read").json()["read"] is True;assert client.post(f"/api/v1/notifications/{notification['id']}/dismiss").json()["dismissed"] is True
   note=client.post("/api/v1/notes",json={"scope_type":"COURSE","scope_id":course_id,"body":"Review aggregate coverage"}).json();assert client.put(f"/api/v1/notes/{note['id']}",json={"body":"Updated","review_status":"REVIEWED","version":99}).status_code==409;assert client.put(f"/api/v1/notes/{note['id']}",json={"body":"Updated","review_status":"REVIEWED","version":1}).json()["version"]==2
   report=client.get(f"/api/v1/aggregate-report?course_id={course_id}");assert report.status_code==200 and "available_sessions" in report.text
 finally:settings.auth_enabled=old

def test_course_crud_assignment_and_archive_safety():
 with TestClient(app) as client:
  room=client.post("/api/v1/classrooms",json={"name":"P4 CRUD room","total_students":10,"total_seats":12}).json();course=client.post("/api/v1/courses",json={"code":"CRUD","name":"Course","classroom_id":room["id"]}).json();session=client.post("/api/sessions",json={"name":"P4 course session","classroom_id":room["id"]}).json()
  assert client.post(f"/api/v1/courses/{course['id']}/sessions",json={"session_id":session["id"]}).status_code==200
  assert client.get(f"/api/v1/courses/{course['id']}/sessions").json()[0]["id"]==session["id"]
  assert client.post(f"/api/v1/classrooms/{room['id']}/archive").json()["active"] is False
  assert client.post(f"/api/v1/classrooms/{room['id']}/archive?restore=true").json()["active"] is True

def test_calendar_buckets_rolling_sparse_evidence_and_methodology_warnings():
 with SessionLocal() as db:
  room=models.Classroom(name="P4 calendar room",total_students=20,total_seats=20);db.add(room);db.flush();course=models.Course(code="CALENDAR",name="Calendar evidence",classroom_id=room.id);db.add(course);db.flush();a=models.Session(name="January one",status="COMPLETED",classroom_id=room.id,course_id=course.id,activity_context="LECTURE",created_at=datetime(2026,1,1,10));b=models.Session(name="January two",status="COMPLETED",classroom_id=room.id,course_id=course.id,activity_context="LECTURE",created_at=datetime(2026,1,2,10));c=models.Session(name="February sparse",status="COMPLETED",classroom_id=room.id,course_id=course.id,activity_context="LECTURE",created_at=datetime(2026,2,1,10));db.add_all([a,b,c]);db.flush();db.add_all([models.AnalyticsSnapshot(session_id=a.id,timestamp=1,student_count=8,engagement_score=60,details={"metrics":{"observable_participation":metric_envelope("observable_participation",60,valid_observations=8,eligible_observations=8)}}),models.AnalyticsSnapshot(session_id=b.id,timestamp=1,student_count=8,engagement_score=80,details={"metrics":{"observable_participation":metric_envelope("observable_participation",80,valid_observations=8,eligible_observations=8)}}),models.EvidenceFusionResult(session_id=a.id,methodology_version="1",status="AVAILABLE",value=60,confidence=.8,coverage={},components=[],limitations=[],weights={}),models.EvidenceFusionResult(session_id=b.id,methodology_version="2",status="AVAILABLE",value=80,confidence=.6,coverage={},components=[],limitations=[],weights={})]);db.commit();course_id,a_id,b_id=course.id,a.id,b.id
 with TestClient(app) as client:
  daily=client.get(f"/api/v1/analytics/trends?course_id={course_id}&period=daily&rolling_window=2&data_source=ALL").json();assert {p["bucket"] for p in daily["points"]}=={"2026-01-01","2026-01-02","2026-02-01"};assert next(p for p in daily["points"] if p["bucket"]=="2026-02-01")["observable_participation"] is None
  monthly=client.get(f"/api/v1/analytics/trends?course_id={course_id}&period=monthly&data_source=ALL").json();assert {p["bucket"] for p in monthly["points"]}=={"2026-01","2026-02"}
  assert client.get(f"/api/v1/analytics/trends?course_id={course_id}&start_date=2026-03-01&end_date=2026-01-01").status_code==400
  comparison=client.post("/api/v1/analytics/compare",json={"session_ids":[a_id,b_id],"metrics":["observable_participation","audio_quality"]}).json();assert comparison["status"]=="PARTIAL_EVIDENCE";assert any("different methodology" in warning.lower() for warning in comparison["warnings"]);assert any("unavailable values were not converted to zero" in warning.lower() for warning in comparison["warnings"])
