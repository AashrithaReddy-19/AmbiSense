import time
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from backend.app import models
from backend.app.auth import hash_password
from backend.app.config import get_settings
from backend.app.database import Base,SessionLocal,engine
from backend.app.main import app

def _security_settings():
    settings=get_settings();previous=(settings.auth_enabled,settings.auth_mode,settings.auth_secret_key,settings.auth_access_token_expire_minutes)
    settings.auth_enabled=True;settings.auth_mode="TOKEN";settings.auth_secret_key="priority-four-test-secret-key-32-characters";settings.auth_access_token_expire_minutes=60
    return settings,previous

def _restore(settings,previous):
    settings.auth_enabled,settings.auth_mode,settings.auth_secret_key,settings.auth_access_token_expire_minutes=previous

def test_signed_login_logout_and_disabled_account_rejection():
    Base.metadata.create_all(engine);settings,previous=_security_settings()
    try:
        with SessionLocal() as db:
            user=models.User(email="security-admin@test",display_name="Security Admin",role="ADMINISTRATOR",password_hash=hash_password("StrongPassword!123"));db.add(user);db.commit();user_id=user.id
        with TestClient(app) as client:
            assert client.post("/api/v1/auth/login",json={"email":"security-admin@test","password":"wrong"}).status_code==401
            login=client.post("/api/v1/auth/login",json={"email":"security-admin@test","password":"StrongPassword!123"});assert login.status_code==200
            headers={"Authorization":f"Bearer {login.json()['access_token']}"};assert client.get("/api/v1/auth/me",headers=headers).json()["role"]=="ADMINISTRATOR"
            assert client.post("/api/v1/auth/logout",headers=headers).status_code==200
            assert client.get("/api/v1/auth/me",headers=headers).status_code==401
        with SessionLocal() as db:db.get(models.User,user_id).active=False;db.commit()
        with TestClient(app) as client:assert client.post("/api/v1/auth/login",json={"email":"security-admin@test","password":"StrongPassword!123"}).status_code==401
    finally:_restore(settings,previous)

def test_expired_token_resource_isolation_and_websocket_auth():
    Base.metadata.create_all(engine);settings,previous=_security_settings()
    try:
        with SessionLocal() as db:
            owner=models.User(email="security-owner@test",display_name="Owner",role="INSTRUCTOR",password_hash=hash_password("StrongPassword!123"));viewer=models.User(email="security-viewer@test",display_name="Viewer",role="VIEWER",password_hash=hash_password("StrongPassword!123"));db.add_all([owner,viewer]);db.flush();room=models.Classroom(name="Protected room",total_students=10,total_seats=10,owner_user_id=owner.id);db.add(room);db.flush();session=models.Session(name="Protected session",classroom_id=room.id);db.add(session);db.commit();session_id=session.id
        with TestClient(app) as client:
            login=client.post("/api/v1/auth/login",json={"email":"security-viewer@test","password":"StrongPassword!123"}).json();headers={"Authorization":f"Bearer {login['access_token']}"}
            assert client.get(f"/api/sessions/{session_id}",headers=headers).status_code==403
            try:
                with client.websocket_connect(f"/ws/sessions/{session_id}?access_token={login['access_token']}"):pass
                assert False,"Cross-resource WebSocket should be rejected"
            except WebSocketDisconnect as error:assert error.code==1008
            settings.auth_access_token_expire_minutes=-1
            expired=client.post("/api/v1/auth/login",json={"email":"security-viewer@test","password":"StrongPassword!123"}).json()["access_token"]
            time.sleep(.01);assert client.get("/api/v1/auth/me",headers={"Authorization":f"Bearer {expired}"}).status_code==401
    finally:_restore(settings,previous)

def test_legacy_lists_search_nested_resources_exports_and_memberships_are_isolated():
    Base.metadata.create_all(engine);settings,previous=_security_settings()
    try:
        with SessionLocal() as db:
            owner=models.User(email="audit-owner@test",display_name="Audit Owner",role="INSTRUCTOR",password_hash=hash_password("StrongPassword!123"));reviewer=models.User(email="audit-reviewer@test",display_name="Audit Reviewer",role="REVIEWER",password_hash=hash_password("StrongPassword!123"));db.add_all([owner,reviewer]);db.flush();room=models.Classroom(name="Audit private room",total_students=10,total_seats=10,owner_user_id=owner.id);db.add(room);db.flush();course=models.Course(code="AUDIT",name="Audit course",classroom_id=room.id,owner_user_id=owner.id);db.add(course);db.flush();session=models.Session(name="Audit secret session",status="COMPLETED",classroom_id=room.id,course_id=course.id);db.add(session);db.flush();snapshot=models.AnalyticsSnapshot(session_id=session.id,timestamp=1,student_count=5,engagement_score=66,attention_score=70);segment=models.TranscriptSegment(id="audit-segment",session_id=session.id,start_seconds=0,end_seconds=2,original_text="private audit concept",confidence=.8,provider="TEST");content=models.GeneratedContentItem(session_id=session.id,content_type="CONCEPT",ordinal=0,text="private concept",confidence=.8,provider="TEST");note=models.CollaborationNote(scope_type="SESSION",scope_id=session.id,author_user_id=owner.id,body="private note");db.add_all([snapshot,segment,content,note]);db.commit();owner_id,reviewer_id,course_id,session_id,content_id,note_id=owner.id,reviewer.id,course.id,session.id,content.id,note.id
        with TestClient(app) as client:
            owner_token=client.post("/api/v1/auth/login",json={"email":"audit-owner@test","password":"StrongPassword!123"}).json()["access_token"];reviewer_token=client.post("/api/v1/auth/login",json={"email":"audit-reviewer@test","password":"StrongPassword!123"}).json()["access_token"];owner_headers={"Authorization":f"Bearer {owner_token}"};reviewer_headers={"Authorization":f"Bearer {reviewer_token}"}
            assert all(row["id"]!=session_id for row in client.get("/api/sessions",headers=reviewer_headers).json())
            assert all(row["session_id"]!=session_id for row in client.post("/api/search",headers=reviewer_headers,json={"query":"private audit concept transcript"}).json()["matches"])
            assert all(row.get("id")!=session_id for row in client.get("/api/reports",headers=reviewer_headers).json())
            assert client.get(f"/api/v1/notes?scope_type=SESSION&scope_id={session_id}",headers=reviewer_headers).status_code==403
            assert client.put(f"/api/v1/notes/{note_id}",headers=reviewer_headers,json={"body":"changed","review_status":"OPEN","version":1}).status_code==403
            assert client.put(f"/api/v1/content-items/{content_id}",headers=reviewer_headers,json={"edited_text":"changed"}).status_code==403
            assert client.get(f"/api/v1/aggregate-report?course_id={course_id}&format=json",headers=reviewer_headers).status_code==403
            assert client.post(f"/api/v1/sessions/{session_id}/archive",headers=reviewer_headers).status_code==403
            assert client.post(f"/api/v1/courses/{course_id}/members",headers=owner_headers,json={"user_id":reviewer_id,"membership_role":"REVIEWER"}).status_code==200
            assert client.get(f"/api/sessions/{session_id}",headers=reviewer_headers).status_code==200
            assert client.get(f"/api/v1/notes?scope_type=SESSION&scope_id={session_id}",headers=reviewer_headers).status_code==200
            assert client.delete(f"/api/v1/courses/{course_id}/members/{reviewer_id}",headers=owner_headers).status_code==200
            assert client.get(f"/api/sessions/{session_id}",headers=reviewer_headers).status_code==403
    finally:_restore(settings,previous)

def test_role_change_revokes_existing_token_and_final_admin_is_protected():
    Base.metadata.create_all(engine);settings,previous=_security_settings()
    try:
        with SessionLocal() as db:
            for existing in db.query(models.User).filter(models.User.role=="ADMINISTRATOR").all():existing.active=False
            admin=models.User(email="audit-final-admin@test",display_name="Final Admin",role="ADMINISTRATOR",password_hash=hash_password("StrongPassword!123"));target=models.User(email="audit-role-target@test",display_name="Role Target",role="VIEWER",password_hash=hash_password("StrongPassword!123"));db.add_all([admin,target]);db.commit();admin_id,target_id=admin.id,target.id
        with TestClient(app) as client:
            admin_token=client.post("/api/v1/auth/login",json={"email":"audit-final-admin@test","password":"StrongPassword!123"}).json()["access_token"];target_token=client.post("/api/v1/auth/login",json={"email":"audit-role-target@test","password":"StrongPassword!123"}).json()["access_token"];headers={"Authorization":f"Bearer {admin_token}"}
            assert client.put(f"/api/v1/users/{target_id}",headers=headers,json={"display_name":"Role Target","role":"REVIEWER","active":True}).status_code==200
            assert client.get("/api/v1/auth/me",headers={"Authorization":f"Bearer {target_token}"}).status_code==401
            assert client.put(f"/api/v1/users/{admin_id}",headers=headers,json={"display_name":"Final Admin","role":"VIEWER","active":True}).status_code==409
    finally:_restore(settings,previous)
