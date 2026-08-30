from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    classroom_id: int | None = None
    source_type: str = "VIDEO"
    activity_context: str = "LECTURE"
    is_test: bool = False


class SessionRead(BaseModel):
    id: int
    name: str
    status: str
    source_type: str
    source_filename: str | None = None
    job_id: str | None = None
    data_source: str = "REAL"
    progress: float
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    error: str | None
    retry_count: int
    failure_code: str | None
    activity_context: str
    archived: bool
    is_test: bool
    processing_stage: str
    duration: float
    fps: float
    total_frames: int
    processed_frames: int
    processing_speed: float
    eta_seconds: float
    analytics_mode: str
    annotated_video_path: str | None
    model_config = ConfigDict(from_attributes=True)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)


class TranscriptCorrectionUpdate(BaseModel):
    corrected_text: str = Field(min_length=1, max_length=10000)


class SpeakerRoleUpdate(BaseModel):
    role: str = Field(pattern="^(UNKNOWN|INSTRUCTOR|STUDENT|MULTIPLE)$")


class GeneratedContentUpdate(BaseModel):
    edited_text: str = Field(min_length=1, max_length=20000)


class UserCreate(BaseModel):
    email: str = Field(min_length=3,max_length=255)
    display_name: str = Field(min_length=1,max_length=160)
    role: str = Field(pattern="^(ADMINISTRATOR|INSTRUCTOR|REVIEWER|VIEWER)$")
    password: str = Field(min_length=12,max_length=256)

class LoginRequest(BaseModel):
    email: str = Field(min_length=3,max_length=255)
    password: str = Field(min_length=1,max_length=256)

class UserUpdate(BaseModel):
    display_name: str = Field(min_length=1,max_length=160)
    role: str = Field(pattern="^(ADMINISTRATOR|INSTRUCTOR|REVIEWER|VIEWER)$")
    active: bool

class ClassroomCreate(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    description: str | None = Field(default=None,max_length=2000)
    location_label: str | None = Field(default=None,max_length=160)
    total_students: int = Field(default=40,ge=0,le=1000)
    total_seats: int = Field(default=40,ge=0,le=1000)

class CourseCreate(BaseModel):
    code: str = Field(min_length=1,max_length=60)
    name: str = Field(min_length=1,max_length=180)
    description: str | None = Field(default=None,max_length=2000)
    academic_term: str | None = Field(default=None,max_length=100)
    classroom_id: int | None = None

class CourseUpdate(CourseCreate):
    active: bool = True

class CourseSessionAssign(BaseModel):
    session_id: int

class CourseMembershipUpsert(BaseModel):
    user_id: int
    membership_role: str = Field(default="VIEWER",pattern="^(INSTRUCTOR|REVIEWER|VIEWER)$")

class CompareRequest(BaseModel):
    session_ids: list[int] = Field(min_length=2,max_length=20)
    metrics: list[str] = Field(default_factory=lambda:["observable_participation","visual_orientation","audio_quality","question_count"])

class NoteCreate(BaseModel):
    scope_type: str = Field(pattern="^(SESSION|CLASSROOM|COURSE)$")
    scope_id: int
    body: str = Field(min_length=1,max_length=10000)

class NoteUpdate(BaseModel):
    body: str = Field(min_length=1,max_length=10000)
    review_status: str = Field(default="OPEN",pattern="^(OPEN|REVIEWED|RESOLVED)$")
    version: int = Field(ge=1)


class SeatRegion(BaseModel):
    id: str
    x1: float
    y1: float
    x2: float
    y2: float


class SeatConfigurationCreate(BaseModel):
    classroom_id: int
    name: str
    regions: list[SeatRegion]


class RuntimeSettingsUpdate(BaseModel):
    expected_students: int = Field(ge=1, le=500)
    total_seats: int = Field(ge=1, le=500)
    yolo_confidence: float = Field(ge=0.05, le=1)
    tracking_confidence: float = Field(ge=0.05, le=1)
    process_every_n_frames: int = Field(ge=1, le=30)
    ema_alpha: float = Field(ge=0.01, le=1)
    ear_threshold: float = Field(ge=0.05, le=0.6)
    drowsiness_duration: float = Field(ge=0.1, le=20)
    yawn_threshold: float = Field(ge=0.1, le=2)
    yawn_min_duration: float = Field(ge=0.1, le=20)
    head_yaw_threshold: float = Field(ge=1, le=90)
    head_pitch_threshold: float = Field(ge=1, le=90)
    distraction_min_duration: float = Field(ge=0.5, le=60)
    aggregation_interval: float = Field(ge=1, le=60)
    privacy_mode: bool
    show_overlays: bool
    retention_days: int = Field(ge=1, le=3650)
    demo_mode: bool
    audio_analytics_enabled: bool = False
    transcription_provider: str = Field(default="NONE", pattern="^(NONE|FASTER_WHISPER)$")
    transcription_model: str = Field(default="base", min_length=1, max_length=120)
    transcription_language: str = Field(default="auto", min_length=2, max_length=20)
    transcript_retention_days: int = Field(default=30, ge=1, le=3650)
    transcript_retention_enabled: bool = True
    diarization_provider: str = Field(default="NONE", pattern="^(NONE|LOCAL_ADAPTER)$")


class PolygonPoint(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class ClassroomRegionCreate(BaseModel):
    region_key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    region_type: str = Field(default="SEAT", pattern="^(SEAT|ZONE|INSTRUCTOR|PROJECTOR|ENTRANCE|EXIT|EXCLUDED)$")
    polygon: list[PolygonPoint] = Field(min_length=3)
    active: bool = True


class ClassroomLayoutCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    reference_image_path: str | None = None
    regions: list[ClassroomRegionCreate] = Field(default_factory=list)


class EventReviewUpdate(BaseModel):
    review_state: str = Field(pattern="^(UNREVIEWED|CONFIRMED|INCORRECT|UNCERTAIN|EXCLUDED)$")
    reviewer_note: str | None = Field(default=None, max_length=2000)
    included_in_report: bool = True


class ActivitySegmentCreate(BaseModel):
    activity_type: str = Field(pattern="^(LECTURE|EXAMINATION|GROUP_DISCUSSION|LABORATORY|STUDENT_PRESENTATION|INDEPENDENT_WRITING|READING|VIDEO_SCREENING|BREAK|CUSTOM)$")
    custom_label: str | None = Field(default=None, max_length=120)
    start_seconds: float = Field(ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    confirmed: bool = True


class BulkArchiveRequest(BaseModel):
    session_ids: list[int] = Field(min_length=1, max_length=500)


class HeatMapRequest(BaseModel):
    metric: str = Field(pattern="^(occupancy|raised_hands|participation|camera_visibility|model_confidence)$")
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    aggregation_interval: float = Field(default=5, ge=1, le=300)
    region_ids: list[str] = Field(default_factory=list)
    compare_session_id: int | None = None
