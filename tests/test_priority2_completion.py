from datetime import datetime, timedelta

import cv2
import numpy as np
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.timeutil import utc_now_naive
from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import Session, StudentObservation
from backend.app.services.cleanup import cleanup_test_sessions


def test_reference_upload_preview_heatmap_and_bulk_archive():
    image=np.full((100,160,3),120,dtype=np.uint8); ok,encoded=cv2.imencode('.jpg',image); assert ok
    with TestClient(app) as client:
        classroom=client.get('/api/v1/classrooms').json()[0]; classroom_id=classroom['id']
        upload=client.post(f'/api/v1/classrooms/{classroom_id}/reference-image',files={'file':('reference.jpg',encoded.tobytes(),'image/jpeg')})
        assert upload.status_code==200 and upload.json()['status']=='AVAILABLE'
        assert client.get(f'/api/v1/classrooms/{classroom_id}/reference-image').headers['content-type']=='image/jpeg'
        layouts=client.get(f'/api/v1/classrooms/{classroom_id}/layouts').json()
        if not layouts:
            layout=client.post(f'/api/v1/classrooms/{classroom_id}/layouts',json={'name':'Completion layout','regions':[{'region_key':'all','name':'All','region_type':'ZONE','polygon':[{'x':0,'y':0},{'x':1,'y':0},{'x':1,'y':1},{'x':0,'y':1}]}]}).json()
        else: layout=layouts[0]
        session=client.post('/api/sessions',json={'name':'Priority 2 completion API test','classroom_id':classroom_id}).json(); session_id=session['id']
        region_id=layout['regions'][0]['region_key']
        with SessionLocal() as db:
            db.add(StudentObservation(session_id=session_id,timestamp=1,tracking_id='Track_preview',confidence=.8,bbox=[1,1,20,20],attention_score=70,region_id=region_id)); db.commit()
        preview=client.get(f'/api/v1/sessions/{session_id}/regions/preview').json()
        assert preview['status']=='AVAILABLE' and preview['tracks'][0]['anonymous_track']=='Track_preview'
        heat=client.post(f'/api/v1/sessions/{session_id}/regions/heatmap',json={'metric':'model_confidence','aggregation_interval':5,'compare_session_id':session_id}).json()
        assert heat['status']=='AVAILABLE' and heat['comparison']['status']=='AVAILABLE' and any(cell['status']=='AVAILABLE' for cell in heat['cells'])
        bulk=client.post('/api/v1/sessions/bulk-archive',json={'session_ids':[session_id,999999]}).json()
        assert session_id in bulk['archived'] and 999999 in bulk['not_found']


def test_reference_frame_capture_from_retained_video(tmp_path):
    video=tmp_path/'reference.avi'; writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),5,(160,90)); writer.write(np.full((90,160,3),90,dtype=np.uint8)); writer.release()
    with TestClient(app) as client:
        classroom_id=client.get('/api/v1/classrooms').json()[0]['id']
        with SessionLocal() as db:
            session=Session(name='Reference capture API test',classroom_id=classroom_id,status='STOPPED',is_test=True,video_path=str(video)); db.add(session); db.commit(); db.refresh(session); session_id=session.id
        captured=client.post(f'/api/v1/classrooms/{classroom_id}/reference-image/capture',params={'session_id':session_id,'timestamp':0})
        assert captured.status_code==200 and captured.json()['status']=='AVAILABLE'


def test_cleanup_is_idempotent_and_never_touches_real_sessions():
    settings=get_settings(); previous=(settings.test_session_cleanup_enabled,settings.test_session_cleanup_age_hours,settings.test_session_cleanup_action)
    settings.test_session_cleanup_enabled=True; settings.test_session_cleanup_age_hours=1; settings.test_session_cleanup_action='ARCHIVE'; old=utc_now_naive()-timedelta(hours=2)
    try:
        with SessionLocal() as db:
            test=Session(name='Old API test cleanup',status='STOPPED',is_test=True,created_at=old); real=Session(name='Real classroom evidence',status='STOPPED',is_test=False,created_at=old); db.add_all([test,real]); db.commit(); test_id,real_id=test.id,real.id
            first=cleanup_test_sessions(db,settings); second=cleanup_test_sessions(db,settings)
            assert first['changed']==1 and second['changed']==0
            assert db.get(Session,test_id).archived is True
            assert db.get(Session,real_id).archived is False
            settings.test_session_cleanup_action='DELETE'
            deleted=cleanup_test_sessions(db,settings); repeated=cleanup_test_sessions(db,settings)
            assert deleted['changed']>=1 and repeated['changed']==0
            assert db.get(Session,test_id) is None and db.get(Session,real_id) is not None
    finally:
        settings.test_session_cleanup_enabled,settings.test_session_cleanup_age_hours,settings.test_session_cleanup_action=previous
