from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "AmbiSense"
    database_url: str = f"sqlite:///{(ROOT_DIR / 'ambisense.db').as_posix()}"
    upload_dir: Path = ROOT_DIR / "videos"
    report_dir: Path = ROOT_DIR / "reports"
    classroom_reference_dir: Path = ROOT_DIR / "videos" / "classroom_references"
    log_dir: Path = ROOT_DIR / "logs"
    yolo_model: str = "yolov8n.pt"
    face_landmarker_model: Path = ROOT_DIR / "models" / "face_landmarker.task"
    pose_landmarker_model: Path = ROOT_DIR / "models" / "pose_landmarker_lite.task"
    process_every_n_frames: int = 3
    yolo_confidence: float = 0.35
    tracking_confidence: float = 0.35
    ema_alpha: float = 0.4
    ear_threshold: float = 0.21
    yawn_threshold: float = 0.6
    drowsiness_duration: float = 2.0
    attention_threshold: float = 0.5
    distraction_min_duration: float = 3.0
    aggregation_interval: float = 5.0
    privacy_mode: bool = True
    show_overlays: bool = True
    max_upload_mb: int = 500
    max_video_duration_minutes: int = 180
    live_inference_fps: float = 3.0
    live_frame_width: int = 960
    yawn_min_duration: float = 1.0
    head_yaw_threshold: float = 18.0
    head_pitch_threshold: float = 18.0
    expected_students: int = 40
    total_seats: int = 40
    retention_days: int = 30
    minimum_track_observations: int = 3
    minimum_track_duration: float = 1.0
    track_timeout: float = 3.0
    track_reentry_window: float = 8.0
    track_iou_gate: float = 0.55
    minimum_metric_coverage: float = 0.2
    max_reference_image_mb: int = 10
    test_session_cleanup_enabled: bool = True
    test_session_cleanup_age_hours: int = 24
    test_session_cleanup_action: str = "ARCHIVE"
    test_session_cleanup_interval_minutes: int = 60
    audio_analytics_enabled: bool = False
    audio_sample_rate: int = 16000
    audio_vad_threshold: float = 0.02
    audio_min_voice_seconds: float = 0.3
    transcription_provider: str = "NONE"
    transcription_model: str = "base"
    transcription_language: str = "auto"
    transcript_retention_days: int = 30
    transcript_retention_enabled: bool = True
    diarization_provider: str = "NONE"
    content_generation_provider: str = "DETERMINISTIC"
    evidence_fusion_version: str = "1.0"
    auth_enabled: bool = False
    auth_mode: str = "TOKEN"
    auth_secret_key: str = ""
    auth_access_token_expire_minutes: int = 60
    auth_issuer: str = "ambisense"
    auth_audience: str = "ambisense-api"
    notification_quality_threshold: float = 45.0
    notification_participation_change_threshold: float = 20.0
    log_level: str = "INFO"
    demo_mode: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for folder in (settings.upload_dir, settings.report_dir, settings.log_dir, settings.classroom_reference_dir):
        folder.mkdir(parents=True, exist_ok=True)
    return settings
