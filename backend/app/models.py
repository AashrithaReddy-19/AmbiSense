from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Classroom(Base):
    __tablename__ = "classrooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Classroom A")
    total_students: Mapped[int] = mapped_column(Integer, default=40)
    total_seats: Mapped[int] = mapped_column(Integer, default=40)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int | None] = mapped_column(ForeignKey("classrooms.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="UPLOADED")
    source_type: Mapped[str] = mapped_column(String(24), default="VIDEO")
    video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_stage: Mapped[str] = mapped_column(String(40), default="UPLOADING")
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


class RuntimeSetting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
