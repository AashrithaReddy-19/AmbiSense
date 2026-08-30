from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def ensure_session_columns() -> None:
    """Apply the small additive SQLite migration without deleting existing data."""
    if not settings.database_url.startswith("sqlite") or "sessions" not in inspect(engine).get_table_names():
        return
    existing = {column["name"] for column in inspect(engine).get_columns("sessions")}
    additions = {
        "processing_stage": "VARCHAR(40) DEFAULT 'UPLOADING'",
        "duration": "FLOAT DEFAULT 0", "fps": "FLOAT DEFAULT 0",
        "total_frames": "INTEGER DEFAULT 0", "processed_frames": "INTEGER DEFAULT 0",
        "processing_speed": "FLOAT DEFAULT 0", "eta_seconds": "FLOAT DEFAULT 0",
        "annotated_video_path": "TEXT", "analytics_mode": "VARCHAR(16) DEFAULT 'REAL'",
        "retry_count": "INTEGER DEFAULT 0", "failure_code": "VARCHAR(40)", "internal_error_reference": "VARCHAR(40)",
        "activity_context": "VARCHAR(40) DEFAULT 'LECTURE'", "archived": "BOOLEAN DEFAULT 0", "is_test": "BOOLEAN DEFAULT 0",
        "course_id": "INTEGER",
        "source_filename": "VARCHAR(255)", "job_id": "VARCHAR(40)", "data_source": "VARCHAR(16) DEFAULT 'REAL'",
    }
    with engine.begin() as connection:
        for name, declaration in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE sessions ADD COLUMN {name} {declaration}"))
        connection.execute(text("UPDATE sessions SET is_test=1, data_source='TEST' WHERE lower(name) LIKE 'priority %' OR lower(name) LIKE 'p4 %' OR lower(name) LIKE 'api test%' OR lower(name) LIKE 'acceptance%' OR lower(name) LIKE 'websocket schema test%'"))
    snapshot_columns = {column["name"] for column in inspect(engine).get_columns("analytics_snapshots")}
    observation_columns = {column["name"] for column in inspect(engine).get_columns("student_observations")} if "student_observations" in inspect(engine).get_table_names() else set()
    with engine.begin() as connection:
        for name in ("raised_hands", "looking_down_students", "looking_away_students"):
            if name not in snapshot_columns:
                connection.execute(text(f"ALTER TABLE analytics_snapshots ADD COLUMN {name} INTEGER DEFAULT 0"))
        snapshot_additions={"current_occupancy_count":"INTEGER DEFAULT 0","peak_occupancy_count":"INTEGER DEFAULT 0","occupancy_rate":"FLOAT","estimated_unique_tracks":"INTEGER DEFAULT 0","verified_attendance_rate":"FLOAT"}
        for name,declaration in snapshot_additions.items():
            if name not in snapshot_columns: connection.execute(text(f"ALTER TABLE analytics_snapshots ADD COLUMN {name} {declaration}"))
        if observation_columns and "raised_hand" not in observation_columns:
            connection.execute(text("ALTER TABLE student_observations ADD COLUMN raised_hand BOOLEAN DEFAULT 0"))
        if observation_columns and "region_id" not in observation_columns:
            connection.execute(text("ALTER TABLE student_observations ADD COLUMN region_id VARCHAR(80)"))
    table_names=inspect(engine).get_table_names()
    with engine.begin() as connection:
        if "classrooms" in table_names:
            columns={c["name"] for c in inspect(engine).get_columns("classrooms")}
            for name,declaration in {"building":"VARCHAR(120)","room":"VARCHAR(80)","reference_image_path":"TEXT"}.items():
                if name not in columns: connection.execute(text(f"ALTER TABLE classrooms ADD COLUMN {name} {declaration}"))
            for name,declaration in {"description":"TEXT","location_label":"VARCHAR(160)","active":"BOOLEAN DEFAULT 1","owner_user_id":"INTEGER"}.items():
                if name not in columns: connection.execute(text(f"ALTER TABLE classrooms ADD COLUMN {name} {declaration}"))
        if "events" in table_names:
            columns={c["name"] for c in inspect(engine).get_columns("events")}
            additions={"end_timestamp":"FLOAT","confidence":"FLOAT","region_id":"VARCHAR(80)","affected_tracks":"INTEGER DEFAULT 0","evidence_coverage":"FLOAT","model_version":"VARCHAR(80)","review_state":"VARCHAR(20) DEFAULT 'UNREVIEWED'","reviewer_note":"TEXT","included_in_report":"BOOLEAN DEFAULT 1"}
            for name,declaration in additions.items():
                if name not in columns: connection.execute(text(f"ALTER TABLE events ADD COLUMN {name} {declaration}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
