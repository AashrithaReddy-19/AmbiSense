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
    }
    with engine.begin() as connection:
        for name, declaration in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE sessions ADD COLUMN {name} {declaration}"))
    snapshot_columns = {column["name"] for column in inspect(engine).get_columns("analytics_snapshots")}
    observation_columns = {column["name"] for column in inspect(engine).get_columns("student_observations")} if "student_observations" in inspect(engine).get_table_names() else set()
    with engine.begin() as connection:
        for name in ("raised_hands", "looking_down_students", "looking_away_students"):
            if name not in snapshot_columns:
                connection.execute(text(f"ALTER TABLE analytics_snapshots ADD COLUMN {name} INTEGER DEFAULT 0"))
        if observation_columns and "raised_hand" not in observation_columns:
            connection.execute(text("ALTER TABLE student_observations ADD COLUMN raised_hand BOOLEAN DEFAULT 0"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
