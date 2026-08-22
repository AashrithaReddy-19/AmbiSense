from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    classroom_id: int | None = None
    source_type: str = "VIDEO"


class SessionRead(BaseModel):
    id: int
    name: str
    status: str
    source_type: str
    progress: float
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    error: str | None
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
