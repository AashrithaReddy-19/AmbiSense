"""Run sample clips through the real pipeline, attached to a classroom and course.

This does what an upload does (copy into videos/, create a QUEUED session, run
VideoProcessor) but sets the classroom and course first, so region analytics and
classroom/course dashboards include the result. Sessions are labelled REAL because
the real YOLO/ByteTrack/MediaPipe pipeline produced them; the clips themselves are
synthetic (see scripts/generate_sample_videos.py).

Usage: python scripts/process_sample_videos.py
"""
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
from sqlalchemy import select  # noqa: E402

from backend.app import models  # noqa: E402
from backend.app.config import get_settings  # noqa: E402
from backend.app.database import SessionLocal  # noqa: E402
from backend.app.services.video_processor import VideoProcessor  # noqa: E402

# clip, course code, activity context
PLAN = [
    ("01_lecture_full_room.mp4", "CS101", "LECTURE"),
    ("02_lecture_late_arrivals.mp4", "MATH201", "LECTURE"),
    ("03_small_group_discussion.mp4", "ENG210", "GROUP_DISCUSSION"),
    ("04_seminar_closeup.mp4", "BIO110", "LECTURE"),
]


def main() -> int:
    settings = get_settings()
    settings.demo_mode = False
    for clip, code, context in PLAN:
        source = ROOT / "sample_videos" / clip
        if not source.exists():
            print(f"Missing {source}; run scripts/generate_sample_videos.py first.")
            return 2
        with SessionLocal() as db:
            course = db.scalar(select(models.Course).where(models.Course.code == code))
            if not course:
                print(f"Course {code} not found; run scripts/seed_demo_data.py first.")
                return 2
            destination = settings.upload_dir / f"{uuid.uuid4().hex}{source.suffix}"
            shutil.copyfile(source, destination)
            capture = cv2.VideoCapture(str(destination))
            frames, fps = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)), float(capture.get(cv2.CAP_PROP_FPS))
            capture.release()
            row = models.Session(name=f"{code} · Sample clip · {context.replace('_', ' ').title()}", classroom_id=course.classroom_id, course_id=course.id, activity_context=context,
                                 status="QUEUED", processing_stage="QUEUED", source_type="VIDEO", source_filename=clip, video_path=str(destination), job_id=uuid.uuid4().hex,
                                 data_source="REAL", analytics_mode="REAL", duration=frames / fps, fps=fps, total_frames=frames)
            db.add(row)
            db.commit()
            session_id = row.id
        VideoProcessor(session_id, str(destination), settings).run()
        with SessionLocal() as db:
            row = db.get(models.Session, session_id)
            peak = max((s.student_count for s in row.snapshots), default=0)
            regions = db.scalar(select(models.StudentObservation.id).where(models.StudentObservation.session_id == session_id, models.StudentObservation.region_id.is_not(None)).limit(1))
            print(f"session {session_id:<4} {row.name:<40} {row.status:<10} snapshots={len(row.snapshots):<4} peak people={peak:<3} regions={'yes' if regions else 'no'} {row.error or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
