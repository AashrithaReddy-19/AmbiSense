from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "AmbiSense"
    database_url: str = f"sqlite:///{(ROOT_DIR / 'ambisense.db').as_posix()}"
    upload_dir: Path = ROOT_DIR / "videos"
    report_dir: Path = ROOT_DIR / "reports"
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
    yawn_min_duration: float = 1.0
    head_yaw_threshold: float = 18.0
    head_pitch_threshold: float = 18.0
    expected_students: int = 40
    total_seats: int = 40
    retention_days: int = 30
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
    for folder in (settings.upload_dir, settings.report_dir, settings.log_dir):
        folder.mkdir(parents=True, exist_ok=True)
    return settings
