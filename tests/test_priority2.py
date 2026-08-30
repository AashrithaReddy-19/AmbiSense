from fastapi.testclient import TestClient

from backend.app.cv.regions import assign_region, point_in_polygon
from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models import Event
from backend.app.services.activity_context import context_limitations, metric_relevant


def test_polygon_assignment_uses_normalized_coordinates():
    polygon=[{"x":.1,"y":.1},{"x":.5,"y":.1},{"x":.5,"y":.5},{"x":.1,"y":.5}]
    assert point_in_polygon((.25,.25),polygon)
    assert not point_in_polygon((.8,.8),polygon)
    assert assign_region((250,150),1000,600,[{"region_key":"front_left","polygon":polygon,"active":True}])=="front_left"


def test_activity_context_rules_are_neutral():
    assert "writing" in context_limitations("EXAMINATION","visual_orientation")[0]
    assert not metric_relevant("BREAK","observable_participation")
    assert metric_relevant("LECTURE","observable_participation")


def test_layout_version_session_filters_activity_and_event_review():
    with TestClient(app) as client:
        classrooms=client.get("/api/v1/classrooms").json(); classroom_id=classrooms[0]["id"]
        payload={"name":"Priority 2 test layout","regions":[{"region_key":"front","name":"Front zone","region_type":"ZONE","polygon":[{"x":0,"y":0},{"x":.5,"y":0},{"x":.5,"y":1},{"x":0,"y":1}],"active":True}]}
        first=client.post(f"/api/v1/classrooms/{classroom_id}/layouts",json=payload)
        assert first.status_code==200 and first.json()["version"]>=1
        second=client.post(f"/api/v1/classrooms/{classroom_id}/layouts",json={**payload,"name":"Priority 2 version 2"}).json()
        assert second["version"]==first.json()["version"]+1
        created=client.post("/api/sessions",json={"name":"Priority 2 API test","classroom_id":classroom_id,"activity_context":"LECTURE"}).json(); session_id=created["id"]
        activity=client.post(f"/api/v1/sessions/{session_id}/activities",json={"activity_type":"GROUP_DISCUSSION","start_seconds":5,"confirmed":True})
        assert activity.status_code==200 and activity.json()["activity_type"]=="GROUP_DISCUSSION"
        listing=client.get("/api/v1/sessions",params={"q":"Priority 2","include_tests":True}).json()
        assert any(item["id"]==session_id for item in listing["items"])
        assert client.post(f"/api/v1/sessions/{session_id}/archive").json()["archived"] is True
        regions=client.get(f"/api/v1/sessions/{session_id}/regions").json()
        assert regions["status"]=="CALIBRATED"
        with SessionLocal() as db:
            event=Event(session_id=session_id,timestamp=8,event_type="HAND_RAISED",severity="INFO",message="Anonymous raised-hand event")
            db.add(event); db.commit(); db.refresh(event); event_id=event.id
        reviewed=client.put(f"/api/v1/events/{event_id}/review",json={"review_state":"EXCLUDED","reviewer_note":"False positive","included_in_report":False}).json()
        assert reviewed["review_state"]=="EXCLUDED" and reviewed["included_in_report"] is False
