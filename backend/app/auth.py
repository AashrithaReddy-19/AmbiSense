"""Signed-token authentication and centralized resource authorization."""
import base64,hashlib,hmac,json,os,time
from dataclasses import dataclass
from fastapi import Depends,Header,HTTPException,Request
from sqlalchemy import or_,select
from sqlalchemy.orm import Session
from . import models
from .config import get_settings
from .database import SessionLocal,get_db

PERMISSIONS={"ADMINISTRATOR":{"*"},"INSTRUCTOR":{"classroom:manage","layout:manage","session:upload","session:view","analytics:view","transcript:view","event:review","report:generate","export","course:manage","note:write"},"REVIEWER":{"session:view","analytics:view","transcript:view","event:review","report:generate","export","note:write"},"VIEWER":{"session:view","analytics:view","report:generate"}}
@dataclass(frozen=True)
class Principal:id:int|None;role:str;email:str
def hash_password(password:str)->str:
 salt=os.urandom(16);digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,310000);return f"pbkdf2_sha256$310000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"
def verify_password(password:str,stored:str|None)->bool:
 try:
  algorithm,rounds,salt,digest=(stored or "").split("$");actual=hashlib.pbkdf2_hmac("sha256",password.encode(),base64.urlsafe_b64decode(salt),int(rounds));return algorithm=="pbkdf2_sha256" and hmac.compare_digest(actual,base64.urlsafe_b64decode(digest))
 except Exception:return False
def _b64(data:bytes):return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
def _unb64(data:str):return base64.urlsafe_b64decode(data+"="*(-len(data)%4))
def create_token(user:models.User,settings=None):
 settings=settings or get_settings()
 if len(settings.auth_secret_key)<32:raise HTTPException(503,"AUTH_SECRET_KEY must contain at least 32 characters")
 now=int(time.time());payload={"sub":str(user.id),"role":user.role,"ver":user.token_version,"iat":now,"exp":now+settings.auth_access_token_expire_minutes*60,"iss":settings.auth_issuer,"aud":settings.auth_audience};header={"alg":"HS256","typ":"JWT"};body=f"{_b64(json.dumps(header,separators=(',',':')).encode())}.{_b64(json.dumps(payload,separators=(',',':')).encode())}";signature=_b64(hmac.new(settings.auth_secret_key.encode(),body.encode(),hashlib.sha256).digest());return f"{body}.{signature}"
def decode_token(token:str,settings=None):
 settings=settings or get_settings()
 try:
  head,payload,signature=token.split(".");expected=_b64(hmac.new(settings.auth_secret_key.encode(),f"{head}.{payload}".encode(),hashlib.sha256).digest())
  if not hmac.compare_digest(signature,expected):raise ValueError()
  data=json.loads(_unb64(payload));now=int(time.time())
  if data["exp"]<=now or data["iss"]!=settings.auth_issuer or data["aud"]!=settings.auth_audience:raise ValueError()
  return data
 except Exception as error:raise HTTPException(401,"Invalid or expired access token") from error
def resolve_principal(authorization:str|None,x_user_id:int|None,db:Session):
 settings=get_settings()
 if not settings.auth_enabled:return Principal(None,"ADMINISTRATOR","local-development")
 if authorization and authorization.lower().startswith("bearer "):
  data=decode_token(authorization.split(None,1)[1]);user=db.get(models.User,int(data["sub"]));
  if not user or not user.active or user.token_version!=data["ver"]:raise HTTPException(401,"User is inactive or token was revoked")
  return Principal(user.id,user.role,user.email)
 if settings.auth_mode.upper()=="DEVELOPMENT" and x_user_id is not None:
  user=db.get(models.User,x_user_id)
  if user and user.active:return Principal(user.id,user.role,user.email)
 raise HTTPException(401,"Authentication required")
def principal(authorization:str|None=Header(default=None,alias="Authorization"),x_user_id:int|None=Header(default=None,alias="X-User-Id"),db:Session=Depends(get_db)):return resolve_principal(authorization,x_user_id,db)
def require(permission:str):
 def dependency(user:Principal=Depends(principal)):
  allowed=PERMISSIONS.get(user.role,set())
  if "*" not in allowed and permission not in allowed:raise HTTPException(403,f"Permission required: {permission}")
  return user
 return dependency
def can_access_classroom(db,user,classroom_id):
 if user.role=="ADMINISTRATOR" or classroom_id is None:return True
 room=db.get(models.Classroom,classroom_id)
 if not room:return False
 if room.owner_user_id in {None,user.id}:return True
 return bool(db.scalar(select(models.CourseMembership.id).join(models.Course,models.Course.id==models.CourseMembership.course_id).where(models.Course.classroom_id==classroom_id,models.CourseMembership.user_id==user.id)))
def can_access_session(db,user,session):
 if user.role=="ADMINISTRATOR":return True
 if session.course_id and db.scalar(select(models.Course.id).where(models.Course.id==session.course_id,or_(models.Course.owner_user_id==user.id,models.Course.id.in_(select(models.CourseMembership.course_id).where(models.CourseMembership.user_id==user.id))))):return True
 return can_access_classroom(db,user,session.classroom_id)
def can_access_course(db,user,course_id):
 if user.role=="ADMINISTRATOR" or course_id is None:return True
 course=db.get(models.Course,course_id)
 if not course:return False
 return course.owner_user_id in {None,user.id} or bool(db.scalar(select(models.CourseMembership.id).where(models.CourseMembership.course_id==course_id,models.CourseMembership.user_id==user.id)))
def can_access_note(db,user,note):
 if note.scope_type=="SESSION":
  target=db.get(models.Session,note.scope_id);return bool(target and can_access_session(db,user,target))
 if note.scope_type=="CLASSROOM":return can_access_classroom(db,user,note.scope_id)
 if note.scope_type=="COURSE":return can_access_course(db,user,note.scope_id)
 return False
def authorize_http_request(request:Request):
 settings=get_settings()
 if not settings.auth_enabled:return
 path=request.url.path
 if path in {"/api/health","/api/ready","/api/v1/auth/login"} or path.startswith(("/docs","/openapi")):return
 with SessionLocal() as db:
  raw=request.headers.get("authorization");uid=request.headers.get("x-user-id");user=resolve_principal(raw,int(uid) if uid and uid.isdigit() else None,db)
  parts=path.strip("/").split("/");session=None;classroom_id=None;course_id=None
  for index,value in enumerate(parts):
   if value=="sessions" and index+1<len(parts) and parts[index+1].isdigit():session=db.get(models.Session,int(parts[index+1]))
   if value=="classrooms" and index+1<len(parts) and parts[index+1].isdigit():classroom_id=int(parts[index+1])
   if value=="courses" and index+1<len(parts) and parts[index+1].isdigit():course_id=int(parts[index+1])
  if "reports" in parts:
   idx=parts.index("reports");session=db.get(models.Session,int(parts[idx+1])) if idx+1<len(parts) and parts[idx+1].isdigit() else session
  if "transcript-segments" in parts:
   idx=parts.index("transcript-segments");segment=db.get(models.TranscriptSegment,parts[idx+1]) if idx+1<len(parts) else None;session=db.get(models.Session,segment.session_id) if segment else None
  if "events" in parts and len(parts)>parts.index("events")+1 and parts[parts.index("events")+1].isdigit():
   event=db.get(models.Event,int(parts[parts.index("events")+1]));session=db.get(models.Session,event.session_id) if event else session
  if "content-items" in parts and len(parts)>parts.index("content-items")+1 and parts[parts.index("content-items")+1].isdigit():
   item=db.get(models.GeneratedContentItem,int(parts[parts.index("content-items")+1]));session=db.get(models.Session,item.session_id) if item else session
  if "notes" in parts and len(parts)>parts.index("notes")+1 and parts[parts.index("notes")+1].isdigit():
   note=db.get(models.CollaborationNote,int(parts[parts.index("notes")+1]));
   if note and not can_access_note(db,user,note):raise HTTPException(403,"Note access denied")
  query=request.query_params
  for key in ("session_id","compare_session_id"):
   if query.get(key," ").isdigit():
    candidate=db.get(models.Session,int(query[key]));
    if candidate and not can_access_session(db,user,candidate):raise HTTPException(403,"Session access denied")
  if query.get("classroom_id"," ").isdigit() and not can_access_classroom(db,user,int(query["classroom_id"])):raise HTTPException(403,"Classroom access denied")
  if query.get("course_id"," ").isdigit() and not can_access_course(db,user,int(query["course_id"])):raise HTTPException(403,"Course access denied")
  if session and not can_access_session(db,user,session):raise HTTPException(403,"Session access denied")
  if classroom_id and not can_access_classroom(db,user,classroom_id):raise HTTPException(403,"Classroom access denied")
  if course_id and not can_access_course(db,user,course_id):raise HTTPException(403,"Course access denied")
  write=request.method not in {"GET","HEAD","OPTIONS"}
  if write and user.role=="VIEWER":raise HTTPException(403,"Viewer access is read-only")
  if write and any(x in path for x in ("/transcript-segments","/events/","/content-items")) and user.role not in {"ADMINISTRATOR","INSTRUCTOR","REVIEWER"}:raise HTTPException(403,"Reviewer permission required")
  if write and any(x in path for x in ("/videos/upload","/sessions/start","/classrooms","/courses")) and user.role not in {"ADMINISTRATOR","INSTRUCTOR"}:raise HTTPException(403,"Instructor permission required")
  if write and (path in {"/api/sessions","/api/uploads","/api/seat-configurations"} or "/archive" in path or path.startswith("/api/v1/sessions/bulk-")) and user.role not in {"ADMINISTRATOR","INSTRUCTOR"}:raise HTTPException(403,"Instructor permission required")
  if write and ("/stop" in path or "/activities" in path or (request.method=="DELETE" and "/sessions/" in path)) and user.role not in {"ADMINISTRATOR","INSTRUCTOR"}:raise HTTPException(403,"Instructor permission required")
  if any(x in path for x in ("/settings","/cleanup","/retention","/system/diagnostics","/system/jobs")) and user.role!="ADMINISTRATOR":raise HTTPException(403,"Administrator permission required")
def bulk_accessible_sessions(db,user,sessions):
 """Same rule as can_access_session, evaluated for many sessions with a constant number of queries (no per-row lookups)."""
 sessions=list(sessions)
 if user.role=="ADMINISTRATOR" or not sessions:return sessions
 member_courses=set(db.scalars(select(models.CourseMembership.course_id).where(models.CourseMembership.user_id==user.id)).all())
 owned_courses=set(db.scalars(select(models.Course.id).where(models.Course.owner_user_id==user.id)).all())
 course_ok=member_courses|owned_courses
 classroom_ids={s.classroom_id for s in sessions if s.classroom_id is not None}
 owners={row.id:row.owner_user_id for row in db.execute(select(models.Classroom.id,models.Classroom.owner_user_id).where(models.Classroom.id.in_(classroom_ids))).all()} if classroom_ids else {}
 member_classrooms=set(db.scalars(select(models.Course.classroom_id).where(models.Course.id.in_(member_courses),models.Course.classroom_id.in_(classroom_ids))).all()) if member_courses and classroom_ids else set()
 def classroom_ok(classroom_id):
  if classroom_id is None:return True
  if classroom_id not in owners:return False
  return owners[classroom_id] in {None,user.id} or classroom_id in member_classrooms
 return [s for s in sessions if (s.course_id and s.course_id in course_ok) or classroom_ok(s.classroom_id)]
