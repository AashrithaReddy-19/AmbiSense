from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Classroom(Base):
    __tablename__ = "classrooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Classroom A")
    total_students: Mapped[int] = mapped_column(Integer, default=40)
    total_seats: Mapped[int] = mapped_column(Integer, default=40)
    building: Mapped[str | None] = mapped_column(String(120), nullable=True)
    room: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reference_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int | None] = mapped_column(ForeignKey("classrooms.id"), nullable=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="CREATED")
    source_type: Mapped[str] = mapped_column(String(24), default="VIDEO")
    video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True, index=True)
    data_source: Mapped[str] = mapped_column(String(16), default="REAL", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    internal_error_reference: Mapped[str | None] = mapped_column(String(40), nullable=True)
    activity_context: Mapped[str] = mapped_column(String(40), default="LECTURE")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_stage: Mapped[str] = mapped_column(String(40), default="CREATED")
    duration: Mapped[float] = mapped_column(Float, default=0)
    fps: Mapped[float] = mapped_column(Float, default=0)
    total_frames: Mapped[int] = mapped_column(Integer, default=0)
    processed_frames: Mapped[int] = mapped_column(Integer, default=0)
    processing_speed: Mapped[float] = mapped_column(Float, default=0)
    eta_seconds: Mapped[float] = mapped_column(Float, default=0)
    annotated_video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    analytics_mode: Mapped[str] = mapped_column(String(16), default="REAL")
    snapshots: Mapped[list["AnalyticsSnapshot"]] = relationship(cascade="all, delete-orphan", order_by="AnalyticsSnapshot.timestamp")


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    timestamp: Mapped[float] = mapped_column(Float)
    student_count: Mapped[int] = mapped_column(Integer, default=0)
    visible_faces: Mapped[int] = mapped_column(Integer, default=0)
    attendance: Mapped[float] = mapped_column(Float, default=0)
    attention_score: Mapped[float] = mapped_column(Float, default=0)
    engagement_score: Mapped[float] = mapped_column(Float, default=0)
    fatigue_score: Mapped[float] = mapped_column(Float, default=0)
    drowsiness_count: Mapped[int] = mapped_column(Integer, default=0)
    yawning_count: Mapped[int] = mapped_column(Integer, default=0)
    occupied_seats: Mapped[int] = mapped_column(Integer, default=0)
    empty_seats: Mapped[int] = mapped_column(Integer, default=0)
    noise_level: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    distracted_students: Mapped[int] = mapped_column(Integer, default=0)
    raised_hands: Mapped[int] = mapped_column(Integer, default=0)
    looking_down_students: Mapped[int] = mapped_column(Integer, default=0)
    looking_away_students: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    current_occupancy_count: Mapped[int] = mapped_column(Integer, default=0)
    peak_occupancy_count: Mapped[int] = mapped_column(Integer, default=0)
    occupancy_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_unique_tracks: Mapped[int] = mapped_column(Integer, default=0)
    verified_attendance_rate: Mapped[float | None] = mapped_column(Float, nullable=True)


class SeatConfiguration(Base):
    __tablename__ = "seat_configurations"
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    regions: Mapped[list] = mapped_column(JSON, default=list)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    timestamp: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(255))


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("session_id", "format", name="uq_report_session_format"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    format: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StudentObservation(Base):
    __tablename__ = "student_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    timestamp: Mapped[float] = mapped_column(Float, index=True)
    tracking_id: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    bbox: Mapped[list] = mapped_column(JSON, default=list)
    yaw: Mapped[float | None] = mapped_column(Float, nullable=True)
    pitch: Mapped[float | None] = mapped_column(Float, nullable=True)
    roll: Mapped[float | None] = mapped_column(Float, nullable=True)
    head_direction: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    attention_state: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    attention_score: Mapped[float] = mapped_column(Float, default=0)
    ear: Mapped[float | None] = mapped_column(Float, nullable=True)
    eye_state: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    possible_drowsiness: Mapped[bool] = mapped_column(default=False)
    mar: Mapped[float | None] = mapped_column(Float, nullable=True)
    yawning: Mapped[bool] = mapped_column(default=False)
    raised_hand: Mapped[bool] = mapped_column(default=False)
    region_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    timestamp: Mapped[float] = mapped_column(Float, index=True)
    tracking_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="INFO")
    message: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    end_timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    region_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    affected_tracks: Mapped[int] = mapped_column(Integer, default=0)
    evidence_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    review_state: Mapped[str] = mapped_column(String(20), default="UNREVIEWED")
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    included_in_report: Mapped[bool] = mapped_column(Boolean, default=True)


class RuntimeSetting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnonymousTrack(Base):
    __tablename__ = "anonymous_tracks"
    __table_args__ = (UniqueConstraint("session_id", "track_uuid", name="uq_session_track_uuid"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    track_uuid: Mapped[str] = mapped_column(String(36))
    tracker_local_id: Mapped[int] = mapped_column(Integer)
    first_seen: Mapped[float] = mapped_column(Float)
    last_seen: Mapped[float] = mapped_column(Float)
    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    visible_duration: Mapped[float] = mapped_column(Float, default=0)
    average_confidence: Mapped[float] = mapped_column(Float, default=0)
    last_bbox: Mapped[list] = mapped_column(JSON, default=list)
    region_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expiry_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)


class QualityAssessment(Base):
    __tablename__ = "quality_assessments"
    __table_args__ = (UniqueConstraint("session_id", "timestamp", name="uq_quality_session_time"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    timestamp: Mapped[float] = mapped_column(Float)
    overall_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="UNAVAILABLE")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class ClassroomLayout(Base):
    __tablename__ = "classroom_layouts"
    __table_args__ = (UniqueConstraint("classroom_id", "version", name="uq_classroom_layout_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    reference_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    regions: Mapped[list["ClassroomRegion"]] = relationship(cascade="all, delete-orphan", order_by="ClassroomRegion.id")


class ClassroomRegion(Base):
    __tablename__ = "classroom_regions"
    id: Mapped[int] = mapped_column(primary_key=True)
    layout_id: Mapped[int] = mapped_column(ForeignKey("classroom_layouts.id"), index=True)
    region_key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    region_type: Mapped[str] = mapped_column(String(32), default="SEAT")
    polygon: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ActivitySegment(Base):
    __tablename__ = "activity_segments"
    __table_args__ = (UniqueConstraint("session_id", "start_seconds", name="uq_activity_session_start"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    activity_type: Mapped[str] = mapped_column(String(40))
    custom_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)


class CleanupAudit(Base):
    __tablename__ = "cleanup_audits"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(20))
    result: Mapped[str] = mapped_column(String(20))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AudioAnalysis(Base):
    __tablename__ = "audio_analyses"
    __table_args__ = (UniqueConstraint("session_id", name="uq_audio_analysis_session"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="UNAVAILABLE")
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[float] = mapped_column(Float, default=0)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_status: Mapped[str] = mapped_column(String(24), default="UNAVAILABLE")
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("session_id","start_seconds","end_seconds",name="uq_transcript_session_time"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    start_seconds: Mapped[float] = mapped_column(Float, index=True)
    end_seconds: Mapped[float] = mapped_column(Float)
    original_text: Mapped[str] = mapped_column(Text)
    corrected_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    speaker_role: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    provider: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    generated: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class TranscriptCorrection(Base):
    __tablename__ = "transcript_corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[str] = mapped_column(ForeignKey("transcript_segments.id"), index=True)
    previous_text: Mapped[str] = mapped_column(Text)
    corrected_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SpeakerSegment(Base):
    __tablename__ = "speaker_segments"
    __table_args__ = (UniqueConstraint("session_id","start_seconds","end_seconds",name="uq_speaker_session_time"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    role: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class DiscourseAnalysis(Base):
    __tablename__ = "discourse_analyses"
    __table_args__ = (UniqueConstraint("session_id",name="uq_discourse_session"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    model_version: Mapped[str] = mapped_column(String(80), default="deterministic-1.0")


class LectureChapter(Base):
    __tablename__ = "lecture_chapters"
    __table_args__ = (UniqueConstraint("session_id","start_seconds",name="uq_chapter_session_start"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_segment_ids: Mapped[list] = mapped_column(JSON, default=list)
    generated: Mapped[bool] = mapped_column(Boolean, default=True)


class GeneratedContentItem(Base):
    __tablename__ = "generated_content_items"
    __table_args__ = (UniqueConstraint("session_id","content_type","ordinal",name="uq_content_session_type_order"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    content_type: Mapped[str] = mapped_column(String(40), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_segment_ids: Mapped[list] = mapped_column(JSON, default=list)
    timestamps: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(80))
    generated: Mapped[bool] = mapped_column(Boolean, default=True)


class EvidenceFusionResult(Base):
    __tablename__ = "evidence_fusion_results"
    __table_args__ = (UniqueConstraint("session_id","methodology_version",name="uq_fusion_session_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    methodology_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    components: Mapped[list] = mapped_column(JSON, default=list)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__="users"
    id: Mapped[int]=mapped_column(primary_key=True)
    email: Mapped[str]=mapped_column(String(255),unique=True,index=True)
    display_name: Mapped[str]=mapped_column(String(160))
    role: Mapped[str]=mapped_column(String(24),default="VIEWER")
    active: Mapped[bool]=mapped_column(Boolean,default=True)
    password_hash: Mapped[str | None]=mapped_column(Text,nullable=True)
    token_version: Mapped[int]=mapped_column(Integer,default=0)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)


class Course(Base):
    __tablename__="courses"
    id: Mapped[int]=mapped_column(primary_key=True)
    code: Mapped[str]=mapped_column(String(60),index=True)
    name: Mapped[str]=mapped_column(String(180))
    description: Mapped[str | None]=mapped_column(Text,nullable=True)
    academic_term: Mapped[str | None]=mapped_column(String(100),nullable=True)
    classroom_id: Mapped[int | None]=mapped_column(ForeignKey("classrooms.id"),nullable=True,index=True)
    owner_user_id: Mapped[int | None]=mapped_column(ForeignKey("users.id"),nullable=True,index=True)
    active: Mapped[bool]=mapped_column(Boolean,default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)


class CourseMembership(Base):
    __tablename__="course_memberships"
    __table_args__=(UniqueConstraint("course_id","user_id",name="uq_course_user"),)
    id: Mapped[int]=mapped_column(primary_key=True)
    course_id: Mapped[int]=mapped_column(ForeignKey("courses.id"),index=True)
    user_id: Mapped[int]=mapped_column(ForeignKey("users.id"),index=True)
    membership_role: Mapped[str]=mapped_column(String(24),default="VIEWER")


class Notification(Base):
    __tablename__="notifications"
    __table_args__=(UniqueConstraint("user_id","dedupe_key",name="uq_notification_user_key"),)
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int | None]=mapped_column(ForeignKey("users.id"),nullable=True,index=True)
    session_id: Mapped[int | None]=mapped_column(ForeignKey("sessions.id"),nullable=True,index=True)
    category: Mapped[str]=mapped_column(String(50),index=True)
    title: Mapped[str]=mapped_column(String(180))
    message: Mapped[str]=mapped_column(Text)
    evidence: Mapped[dict]=mapped_column(JSON,default=dict)
    dedupe_key: Mapped[str]=mapped_column(String(180))
    read_at: Mapped[datetime | None]=mapped_column(DateTime,nullable=True)
    dismissed_at: Mapped[datetime | None]=mapped_column(DateTime,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)


class CollaborationNote(Base):
    __tablename__="collaboration_notes"
    id: Mapped[int]=mapped_column(primary_key=True)
    scope_type: Mapped[str]=mapped_column(String(24),index=True)
    scope_id: Mapped[int]=mapped_column(Integer,index=True)
    author_user_id: Mapped[int | None]=mapped_column(ForeignKey("users.id"),nullable=True,index=True)
    body: Mapped[str]=mapped_column(Text)
    review_status: Mapped[str]=mapped_column(String(24),default="OPEN")
    version: Mapped[int]=mapped_column(Integer,default=1)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)


class AuditEntry(Base):
    __tablename__="audit_entries"
    id: Mapped[int]=mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None]=mapped_column(ForeignKey("users.id"),nullable=True,index=True)
    action: Mapped[str]=mapped_column(String(80),index=True)
    resource_type: Mapped[str]=mapped_column(String(40))
    resource_id: Mapped[int | None]=mapped_column(Integer,nullable=True)
    details: Mapped[dict]=mapped_column(JSON,default=dict)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
