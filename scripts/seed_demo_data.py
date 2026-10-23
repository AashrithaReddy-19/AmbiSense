"""Seed the database with clearly labelled DEMO classrooms, courses and sessions.

Each session is simulated per anonymous student per minute (head direction, face
visibility, raised hands, eye closure) and aggregated with the same formulas as the
real pipeline. Snapshots, content extraction, evidence fusion, reports and
notifications are then produced by the application's own code. Every seeded
session has analytics_mode=DEMO and a job_id starting with "demo-seed-".

Usage:
    python scripts/seed_demo_data.py           # add demo data (skips if already seeded)
    python scripts/seed_demo_data.py --reset   # remove previous demo data, then re-seed
    python scripts/seed_demo_data.py --remove  # remove demo data only
"""
import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, insert, select  # noqa: E402

from backend.app import models  # noqa: E402
from backend.app.auth import hash_password  # noqa: E402
from backend.app.config import get_settings  # noqa: E402
from backend.app.cv.attention import AttentionEstimator  # noqa: E402
from backend.app.cv.engagement import calculate_engagement, calculate_fatigue  # noqa: E402
from backend.app.database import Base, SessionLocal, engine, ensure_session_columns  # noqa: E402
from backend.app.metrics import safe_rate  # noqa: E402
from backend.app.services.audio_intelligence import derive_content, fuse  # noqa: E402
from backend.app.services.priority4 import generate_alerts  # noqa: E402
from backend.app.services.report_generator import create_csv_report, create_pdf_report  # noqa: E402
from backend.app.services.video_processor import VideoProcessor  # noqa: E402

JOB_PREFIX = "demo-seed-"
DEMO_PASSWORD = "AmbiSense-Demo-2026"
FRAME_W, FRAME_H = 1280, 720
TODAY = datetime(2026, 10, 23, 18, 0)

USERS = [
    ("admin@ambisense.demo", "Demo Administrator", "ADMINISTRATOR"),
    ("r.iyer@ambisense.demo", "Dr. Ravi Iyer", "INSTRUCTOR"),
    ("m.chen@ambisense.demo", "Prof. Mei Chen", "INSTRUCTOR"),
    ("a.okafor@ambisense.demo", "Ada Okafor", "REVIEWER"),
    ("viewer@ambisense.demo", "Department Viewer", "VIEWER"),
]

# name, building, room, seats, face visibility (front, back), camera quality, owner email
CLASSROOMS = [
    ("Lecture Hall 101", "Science Block", "101", 60, (.85, .5), 78, "r.iyer@ambisense.demo"),
    ("Physics Lab B2", "Engineering Wing", "B2", 30, (.55, .35), 42, "m.chen@ambisense.demo"),
    ("Seminar Room 3", "Humanities Building", "3", 20, (.92, .85), 86, "m.chen@ambisense.demo"),
]

# code, name, term, classroom name, enrolled, base attention, owner, schedule (weekday, hour), contexts
COURSES = [
    ("CS101", "Introduction to Programming", "Fall 2026", "Lecture Hall 101", 54, 74, "r.iyer@ambisense.demo", [(0, 9), (2, 9)],
     ["LECTURE", "LECTURE", "GROUP_DISCUSSION", "LECTURE", "LECTURE", "EXAMINATION", "LECTURE", "LECTURE"]),
    ("MATH201", "Linear Algebra", "Fall 2026", "Lecture Hall 101", 46, 66, "r.iyer@ambisense.demo", [(1, 11), (3, 11)],
     ["LECTURE", "LECTURE", "LECTURE", "EXAMINATION", "LECTURE", "LECTURE", "LECTURE"]),
    ("PHY120", "Physics Laboratory", "Fall 2026", "Physics Lab B2", 26, 70, "m.chen@ambisense.demo", [(1, 14)],
     ["LABORATORY", "LABORATORY", "LECTURE", "LABORATORY", "LABORATORY", "LABORATORY"]),
    ("ENG210", "Academic Writing Seminar", "Fall 2026", "Seminar Room 3", 18, 80, "m.chen@ambisense.demo", [(0, 13), (3, 13)],
     ["GROUP_DISCUSSION", "STUDENT_PRESENTATION", "INDEPENDENT_WRITING", "GROUP_DISCUSSION", "STUDENT_PRESENTATION", "GROUP_DISCUSSION", "READING"]),
    ("BIO110", "Foundations of Biology", "Fall 2026", "Classroom A", 34, 71, "r.iyer@ambisense.demo", [(4, 10)],
     ["LECTURE", "VIDEO_SCREENING", "LECTURE", "READING", "LECTURE", "LECTURE"]),
]

# Direction probabilities (FRONT, DOWN, LEFT, RIGHT, UP) per activity at full attention.
DIRECTIONS = ["FRONT", "DOWN", "LEFT", "RIGHT", "UP"]
CONTEXT_PROFILE = {
    "LECTURE": ((.82, .10, .03, .03, .02), .04, 1.0),
    "GROUP_DISCUSSION": ((.30, .12, .27, .27, .04), .09, 1.1),
    "STUDENT_PRESENTATION": ((.80, .10, .04, .04, .02), .05, 1.0),
    "EXAMINATION": ((.12, .82, .02, .02, .02), .005, .7),
    "INDEPENDENT_WRITING": ((.15, .78, .03, .03, .01), .01, .8),
    "READING": ((.18, .74, .03, .03, .02), .01, .9),
    "VIDEO_SCREENING": ((.86, .06, .03, .03, .02), .01, 1.4),
    "LABORATORY": ((.35, .40, .11, .11, .03), .03, .9),
}
STATE = {"FRONT": "ATTENTIVE", "DOWN": "LOOKING_DOWN", "LEFT": "LOOKING_LEFT", "RIGHT": "LOOKING_RIGHT", "UP": "LOOKING_AWAY"}

TRANSCRIPTS = {
    "CS101": ["Today we look at how a program stores values in variables.", "A variable means a named location that holds a value.", "Why do we need different data types for numbers and text?",
              "A loop is defined as a block of code that repeats while a condition is true.", "Let us trace this for loop line by line on the board.", "What happens if the loop condition never becomes false?",
              "A function refers to a reusable block of code with inputs and an output.", "Recursion means a function that calls itself on a smaller problem.", "Can someone suggest the base case for this factorial example?",
              "Lists keep items in order and let us index from zero.", "Debugging is the process of finding and fixing errors in code.", "For the lab, write a function that reverses a list."],
    "MATH201": ["We start with vectors and how to add them component by component.", "A matrix means a rectangular array of numbers.", "What does it mean for two vectors to be linearly independent?",
                "The determinant is defined as a scalar that tells us whether a matrix is invertible.", "Row reduction gives us the echelon form of the system.", "Why does a zero determinant mean there is no unique solution?",
                "An eigenvector refers to a vector whose direction is unchanged by the transformation.", "Let us compute the eigenvalues of this two by two matrix.", "Is the matrix diagonalizable if an eigenvalue repeats?",
                "Orthogonal vectors have a dot product of zero.", "Projection means finding the closest point in a subspace."],
    "PHY120": ["Today's experiment measures the period of a simple pendulum.", "Uncertainty means the range within which the true value is expected to lie.", "Why should we time ten oscillations instead of one?",
               "Record the length from the pivot to the centre of the bob.", "Acceleration due to gravity is defined as the rate of change of velocity for a falling object.", "What sources of systematic error can you identify?",
               "Plot the period squared against the length.", "The gradient of this graph relates to gravitational acceleration.", "Does the amplitude affect the period for small angles?"],
    "ENG210": ["Today each group will critique the thesis statements from last week.", "A thesis means the central claim your essay will defend.", "How specific should a thesis be for a five page paper?",
               "Evidence refers to sources and data that support your claim.", "Let us discuss how to integrate quotations smoothly.", "What is the difference between paraphrasing and summarising?",
               "A counterargument is defined as a reasonable objection to your position.", "Presenters, please summarise your argument in two minutes.", "Which transition words help signal a contrast?"],
    "BIO110": ["We begin with the structure of the animal cell.", "Photosynthesis means converting light energy into chemical energy.", "Why is chlorophyll green?",
               "The mitochondrion is defined as the organelle that produces most of the cell's ATP.", "Let us compare plant and animal cells on this diagram.", "What would happen to a cell without a functioning membrane?",
               "Osmosis refers to the movement of water across a semi-permeable membrane.", "DNA carries the genetic instructions for building proteins.", "How does an enzyme lower activation energy?"],
}
NOTES = [
    ("Lower participation in the last 15 minutes of most CS101 lectures; consider a short activity break around minute 35.", "OPEN"),
    ("Camera in Physics Lab B2 is backlit by the window in the afternoon; face coverage is low, so treat orientation values cautiously.", "REVIEWED"),
    ("Exam session: looking down is expected and visual orientation is excluded from fusion.", "RESOLVED"),
]


def remove_demo(db):
    ids = db.scalars(select(models.Session.id).where(models.Session.job_id.like(f"{JOB_PREFIX}%"))).all()
    if ids:
        segment_ids = select(models.TranscriptSegment.id).where(models.TranscriptSegment.session_id.in_(ids))
        db.execute(delete(models.TranscriptCorrection).where(models.TranscriptCorrection.segment_id.in_(segment_ids)))
        for model in (models.StudentObservation, models.AnalyticsSnapshot, models.Event, models.Alert, models.Report, models.AnonymousTrack, models.QualityAssessment, models.ActivitySegment,
                      models.SpeakerSegment, models.DiscourseAnalysis, models.LectureChapter, models.GeneratedContentItem, models.EvidenceFusionResult, models.TranscriptSegment, models.AudioAnalysis, models.Notification):
            db.execute(delete(model).where(model.session_id.in_(ids)))
        db.execute(delete(models.CollaborationNote).where(models.CollaborationNote.scope_type == "SESSION", models.CollaborationNote.scope_id.in_(ids)))
        db.execute(delete(models.Session).where(models.Session.id.in_(ids)))
    course_ids = db.scalars(select(models.Course.id).where(models.Course.code.in_([c[0] for c in COURSES]))).all()
    db.execute(delete(models.CollaborationNote).where(models.CollaborationNote.scope_type == "COURSE", models.CollaborationNote.scope_id.in_(course_ids)))
    db.execute(delete(models.CourseMembership).where(models.CourseMembership.course_id.in_(course_ids)))
    db.execute(delete(models.Course).where(models.Course.id.in_(course_ids)))
    rooms = db.scalars(select(models.Classroom).where(models.Classroom.name.in_([c[0] for c in CLASSROOMS]))).all()
    for room in rooms:
        for layout in db.scalars(select(models.ClassroomLayout).where(models.ClassroomLayout.classroom_id == room.id)).all():
            db.delete(layout)
        db.delete(room)
    db.flush()
    user_ids = db.scalars(select(models.User.id).where(models.User.email.in_([u[0] for u in USERS]))).all()
    db.execute(delete(models.Notification).where(models.Notification.user_id.in_(user_ids)))
    db.execute(delete(models.AuditEntry).where(models.AuditEntry.actor_user_id.in_(user_ids)))
    db.execute(delete(models.User).where(models.User.id.in_(user_ids)))
    db.commit()
    return len(ids)


def make_layout(db, classroom):
    layout = models.ClassroomLayout(classroom_id=classroom.id, name="Demo zones", version=(db.scalar(select(models.ClassroomLayout.version).where(models.ClassroomLayout.classroom_id == classroom.id).order_by(models.ClassroomLayout.version.desc())) or 0) + 1, active=True)
    for prior in db.scalars(select(models.ClassroomLayout).where(models.ClassroomLayout.classroom_id == classroom.id, models.ClassroomLayout.active.is_(True))).all():
        prior.active = False
    box = lambda x1, y1, x2, y2: [{"x": x1, "y": y1}, {"x": x2, "y": y1}, {"x": x2, "y": y2}, {"x": x1, "y": y2}]
    layout.regions = [
        models.ClassroomRegion(region_key="instructor", name="Instructor area", region_type="INSTRUCTOR", polygon=box(.25, 0, .75, .25)),
        models.ClassroomRegion(region_key="front_left", name="Front left", region_type="ZONE", polygon=box(0, .25, .5, .5)),
        models.ClassroomRegion(region_key="front_right", name="Front right", region_type="ZONE", polygon=box(.5, .25, 1, .5)),
        models.ClassroomRegion(region_key="middle", name="Middle rows", region_type="ZONE", polygon=box(0, .5, 1, .75)),
        models.ClassroomRegion(region_key="back", name="Back rows", region_type="ZONE", polygon=box(0, .75, 1, 1)),
    ]
    db.add(layout)
    return layout


def region_for(x, y):
    if y < .5:
        return "front_left" if x < .5 else "front_right"
    return "middle" if y < .75 else "back"


def session_dates(schedule, count):
    """The most recent `count` class meetings before TODAY for a weekly schedule."""
    dates, day = [], TODAY - timedelta(days=1)
    while len(dates) < count:
        for weekday, hour in schedule:
            if day.weekday() == weekday:
                dates.append(day.replace(hour=hour, minute=random.choice((0, 5, 10)), second=0, microsecond=0))
        day -= timedelta(days=1)
    return sorted(dates[:count])


def simulate_session(db, rng, settings, session, course, room, week_index, total_weeks):
    code, enrolled, base_attention, context = course["code"], course["enrolled"], course["attention"], session.activity_context
    weights, hand_rate, drowsy_factor = CONTEXT_PROFILE[context]
    duration_min = 75 if context == "LABORATORY" else 50
    room_settings = settings.model_copy(update={"total_seats": room["seats"], "expected_students": enrolled})
    processor = VideoProcessor(session.id, "", room_settings)
    attention = AttentionEstimator(room_settings.ema_alpha)
    front_vis, back_vis = room["visibility"]
    trend = 4 * (week_index / max(1, total_weeks - 1)) - 2
    students = []
    for _ in range(enrolled):
        x, y = rng.uniform(.04, .96), rng.uniform(.3, .97)
        students.append({"id": f"Track_{uuid.uuid4().hex[:8]}", "x": x, "y": y, "focus": rng.gauss(0, .08), "arrive": max(0, rng.gauss(1, 2.5)) if rng.random() < .25 else 0,
                         "absent": rng.random() < (.06 + .04 * (context == "LECTURE") + .03 * (week_index > total_weeks * .6)), "leave": duration_min - rng.uniform(1, 8) if rng.random() < .08 else 999, "hand": False, "first": None, "last": None, "obs": 0})
    observation_rows, events, yawns, last_event = [], [], 0, {}
    for minute in range(duration_min + 1):
        t = minute * 60.0
        progress = minute / duration_min
        level = (base_attention + trend) / 100 - .18 * max(0, progress - .45) + .05 * (context in {"GROUP_DISCUSSION", "STUDENT_PRESENTATION"}) * (1 - progress)
        present = [s for s in students if not s["absent"] and s["arrive"] <= minute <= s["leave"]]
        rows = []
        for s in present:
            p_front = min(.97, max(.05, weights[0] * (level + s["focus"]) / .75))
            rest = [w for w in weights[1:]]
            scale = (1 - p_front) / sum(rest)
            direction = rng.choices(DIRECTIONS, [p_front] + [w * scale for w in rest])[0]
            visible = rng.random() < front_vis + (back_vis - front_vis) * (s["y"] - .3) / .67
            drowsy = visible and rng.random() < drowsy_factor * (.004 + .03 * max(0, progress - .5)) * (1.4 if s["focus"] < -.05 else 1)
            if visible and rng.random() < drowsy_factor * .0015 * (1 + 3 * progress):
                yawns += 1
            hand = rng.random() < hand_rate * (1.2 if s["y"] < .5 else .8)
            if visible:
                state = STATE[direction]
                score = float(attention.estimate(s["id"], direction)["score"])
                if drowsy:
                    state, score = "LOOKING_DOWN", min(score, 25.0)
            else:
                state, score = "UNKNOWN", 0.0
            region = region_for(s["x"], s["y"])
            bw, bh = 70 + 50 * (1 - s["y"]), 140 + 90 * (1 - s["y"])
            bx, by = s["x"] * FRAME_W - bw / 2, s["y"] * FRAME_H - bh / 2
            row = {"tracking_id": s["id"], "direction": direction if visible else "UNKNOWN", "attention_state": state, "attention_score": score, "drowsiness": drowsy, "raised_hand": hand}
            rows.append(row)
            s["first"] = t if s["first"] is None else s["first"]
            s["last"], s["obs"] = t, s["obs"] + 1
            if minute % 2 == 0:
                yaw = rng.uniform(-30, -19) if direction == "LEFT" else rng.uniform(19, 30) if direction == "RIGHT" else rng.uniform(-12, 12)
                pitch = rng.uniform(19, 35) if direction == "DOWN" else rng.uniform(-30, -19) if direction == "UP" else rng.uniform(-10, 10)
                observation_rows.append({"session_id": session.id, "timestamp": t, "tracking_id": s["id"], "confidence": round(rng.uniform(.55, .93), 3), "bbox": [round(bx, 1), round(by, 1), round(bx + bw, 1), round(by + bh, 1)],
                                         "yaw": round(yaw, 2) if visible else None, "pitch": round(pitch, 2) if visible else None, "roll": round(rng.uniform(-6, 6), 2) if visible else None, "head_direction": row["direction"],
                                         "attention_state": state, "attention_score": score, "ear": round(rng.uniform(.13, .19) if drowsy else rng.uniform(.24, .33), 3) if visible else None,
                                         "eye_state": ("CLOSED" if drowsy else "OPEN") if visible else "UNKNOWN", "possible_drowsiness": drowsy, "mar": round(rng.uniform(.1, .35), 3) if visible else None,
                                         "yawning": False, "raised_hand": hand, "region_id": region})
            if hand != s["hand"] and hand:
                events.append(models.Event(session_id=session.id, timestamp=t, end_timestamp=t + rng.uniform(3, 12), tracking_id=s["id"], event_type="HAND_RAISED", severity="INFO", message=f"{s['id']}: hand raised",
                                           confidence=round(rng.uniform(.6, .9), 2), region_id=region, affected_tracks=1))
            if drowsy and t - last_event.get(s["id"], -999) >= 300:
                events.append(models.Event(session_id=session.id, timestamp=t, end_timestamp=t + 2, tracking_id=s["id"], event_type="POSSIBLE_DROWSINESS", severity="WARNING", message=f"{s['id']}: possible prolonged eye closure",
                                           confidence=round(rng.uniform(.5, .8), 2), region_id=region, affected_tracks=1))
                last_event[s["id"]] = t
            s["hand"] = hand
        aggregate(db, processor, rng, session, t, rows, yawns, events, last_event, enrolled)
        if minute % 5 == 0:
            quality = max(15, min(97, room["camera"] + rng.gauss(0, 6) - (8 if context == "LABORATORY" and minute > 40 else 0)))
            faces = sum(r["direction"] != "UNKNOWN" for r in rows)
            warnings = (["Video is underexposed."] if quality < 45 else []) + (["Visual orientation has insufficient face-landmark coverage."] if rows and faces / len(rows) < .25 else [])
            db.add(models.QualityAssessment(session_id=session.id, timestamp=t, overall_quality=round(quality, 2), status="GOOD" if quality >= 70 else "LIMITED" if quality >= 40 else "POOR",
                                            details={"overall_quality": round(quality, 2), "status": "GOOD" if quality >= 70 else "LIMITED" if quality >= 40 else "POOR", "face_coverage_score": safe_rate(faces, len(rows)), "warnings": warnings}))
    if observation_rows:
        db.execute(insert(models.StudentObservation), observation_rows)
    for event in events:
        roll = rng.random()
        if roll < .12:
            event.review_state, event.reviewer_note = "CONFIRMED", "Checked against the timeline."
        elif roll < .16:
            event.review_state, event.reviewer_note, event.included_in_report = "EXCLUDED", "Student was stretching, not raising a hand.", False
    db.add_all(events)
    for s in students:
        if s["obs"]:
            db.add(models.AnonymousTrack(session_id=session.id, track_uuid=str(uuid.uuid4()), tracker_local_id=rng.randint(1, 999), first_seen=s["first"], last_seen=s["last"], observation_count=s["obs"],
                                         visible_duration=s["last"] - s["first"], average_confidence=round(rng.uniform(.6, .9), 3), last_bbox=[], region_id=region_for(s["x"], s["y"]), active=False, expiry_reason="SESSION_END"))
    return duration_min


def aggregate(db, processor, rng, session, t, rows, yawns, events, last_event, enrolled):
    """Same aggregation as VideoProcessor._aggregate, written with mode DEMO."""
    count = len(rows)
    faces = [r for r in rows if r["direction"] != "UNKNOWN"]
    attention = sum(r["attention_score"] for r in faces) / len(faces) if faces else None
    drowsy = sum(r["drowsiness"] for r in rows)
    looking_down = sum(r["attention_state"] == "LOOKING_DOWN" for r in rows)
    looking_away = sum(r["attention_state"] in {"LOOKING_LEFT", "LOOKING_RIGHT", "LOOKING_AWAY", "DISTRACTED"} for r in rows)
    hands = sum(r["raised_hand"] for r in rows)
    signals = {"attention": attention, "orientation": safe_rate(sum(r["direction"] == "FRONT" for r in faces), len(faces)), "eye_state": safe_rate(len(faces) - drowsy, len(faces)), "activity": safe_rate(count, enrolled)}
    available = {k: v for k, v in signals.items() if v is not None}
    weights = {"attention": .45, "orientation": .20, "eye_state": .15, "activity": .20}
    engagement = float(calculate_engagement(available, {k: weights[k] for k in available})["engagement_score"]) if available else 0
    fatigue = float(calculate_fatigue(safe_rate(drowsy, len(faces)) or 0, min(100, yawns * 5), looking_down / count * 100 if count else 0, max(0, 70 - engagement))["fatigue_score"])
    processor._snapshot(db, t, count, attention or 0, engagement, fatigue, drowsy, yawns, "DEMO", hands, looking_down, looking_away, valid_faces=len(faces))
    for active, kind, severity, message in (
        (looking_away >= max(3, count * .3), "HIGH_DISTRACTION", "WARNING", f"{looking_away} students were estimated as distracted or looking away."),
        (engagement < 40, "LOW_ENGAGEMENT", "WARNING", "Estimated Engagement Index fell below 40."),
        (engagement >= 80, "HIGH_ENGAGEMENT", "INFO", "Estimated Engagement Index exceeded 80."),
        (fatigue >= 65, "HIGH_FATIGUE", "WARNING", "Classroom fatigue indicators reached HIGH."),
        (drowsy >= max(2, count * .2), "DROWSINESS_CLUSTER", "WARNING", f"Possible prolonged eye closure detected for {drowsy} students."),
    ):
        if active and t - last_event.get(kind, -999) >= 600:
            events.append(models.Event(session_id=session.id, timestamp=t, event_type=kind, severity=severity, message=message, details={"student_count": count, "engagement": engagement, "fatigue": fatigue}))
            last_event[kind] = t


def add_audio(db, rng, session, course, duration_min, room):
    if rng.random() < .15:
        db.add(models.AudioAnalysis(session_id=session.id, status="MODEL_DISABLED", quality_status="UNAVAILABLE", limitations=["Audio analytics were disabled for this session."]))
        db.flush()
        derive_content(db, session.id, "MODEL_DISABLED", db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id == session.id)), get_settings())
        return
    noisy = session.activity_context in {"LABORATORY", "GROUP_DISCUSSION"}
    score = max(25, min(95, rng.gauss(62 if noisy else 79, 8) - (10 if room["camera"] < 50 else 0)))
    silence = round(rng.uniform(.35, .6) if session.activity_context in {"EXAMINATION", "INDEPENDENT_WRITING", "READING"} else rng.uniform(.12, .3), 3)
    analysis = models.AudioAnalysis(session_id=session.id, status="AVAILABLE", duration=duration_min * 60.0, sample_rate=16000, quality_status="GOOD" if score >= 70 else "LIMITED" if score >= 40 else "POOR",
                                    quality={"score": round(score, 2), "snr_db_estimate": round(rng.uniform(9, 24), 2), "clipping_ratio": round(rng.uniform(0, .004), 4), "silence_ratio": silence},
                                    coverage={"audio_duration_seconds": duration_min * 60.0, "voiced_ratio": round(1 - silence, 3)}, provider="demo-transcript", model_version="simulated", limitations=["Simulated demo transcript; not a real recording."])
    db.add(analysis)
    db.flush()
    status = "MODEL_DISABLED"
    if session.activity_context not in {"EXAMINATION", "INDEPENDENT_WRITING"}:
        lines = TRANSCRIPTS[course["code"]][:]
        rng.shuffle(lines)
        start = 30.0
        for line in lines + rng.sample(lines, k=min(4, len(lines))):
            if start > duration_min * 60 - 20:
                break
            end = start + rng.uniform(6, 14)
            db.add(models.TranscriptSegment(id=str(uuid.uuid4()), session_id=session.id, start_seconds=round(start, 2), end_seconds=round(end, 2), original_text=line, confidence=round(rng.uniform(.72, .95), 3),
                                            language="en", speaker_role="INSTRUCTOR" if "?" not in line or rng.random() < .5 else "STUDENT", provider="demo-transcript", model_version="simulated", metadata_json={"privacy": "anonymous", "demo": True}))
            start = end + rng.uniform(60, 220)
        db.flush()
        status = "AVAILABLE"
    derive_content(db, session.id, status, analysis, get_settings())


def seed(db):
    settings = get_settings()
    rng = random.Random(2026)
    random.seed(2026)
    users = {}
    for email, name, role in USERS:
        user = db.scalar(select(models.User).where(models.User.email == email)) or models.User(email=email, display_name=name, role=role, password_hash=hash_password(DEMO_PASSWORD))
        db.add(user)
        users[email] = user
    db.flush()
    rooms = {}
    for name, building, room_no, seats, visibility, camera, owner in CLASSROOMS:
        room = models.Classroom(name=name, building=building, room=room_no, location_label=f"{building}, Room {room_no}", description=f"Demo classroom ({seats} seats)", total_seats=seats, total_students=seats, active=True, owner_user_id=users[owner].id)
        db.add(room)
        db.flush()
        make_layout(db, room)
        rooms[name] = {"row": room, "seats": seats, "visibility": visibility, "camera": camera}
    existing = db.scalar(select(models.Classroom).where(models.Classroom.name == "Classroom A"))
    if not existing:
        existing = models.Classroom(name="Classroom A", total_students=40, total_seats=40)
        db.add(existing)
        db.flush()
    if not db.scalar(select(models.ClassroomLayout.id).where(models.ClassroomLayout.classroom_id == existing.id, models.ClassroomLayout.active.is_(True))):
        make_layout(db, existing)
    rooms["Classroom A"] = {"row": existing, "seats": existing.total_seats or 40, "visibility": (.8, .55), "camera": 72}
    db.commit()

    all_sessions, created = [], 0
    for code, name, term, room_name, enrolled, base_attention, owner, schedule, contexts in COURSES:
        room = rooms[room_name]
        course_row = models.Course(code=code, name=name, academic_term=term, classroom_id=room["row"].id, owner_user_id=users[owner].id, description=f"Demo course taught in {room_name}.", active=True)
        db.add(course_row)
        db.flush()
        for email, role in (("a.okafor@ambisense.demo", "REVIEWER"), ("viewer@ambisense.demo", "VIEWER")):
            db.add(models.CourseMembership(course_id=course_row.id, user_id=users[email].id, membership_role=role))
        course = {"code": code, "enrolled": enrolled, "attention": base_attention}
        for index, (when, context) in enumerate(zip(session_dates(schedule, len(contexts)), contexts)):
            week = index + 1
            label = context.replace("_", " ").title()
            session = models.Session(name=f"{code} · Week {week} · {label}", classroom_id=room["row"].id, course_id=course_row.id, status="PROCESSING", processing_stage="PROCESSING", source_type="VIDEO",
                                     source_filename=f"{code.lower()}_week{week:02d}_{context.lower()}.mp4", job_id=f"{JOB_PREFIX}{uuid.uuid4().hex[:16]}", data_source="DEMO", analytics_mode="DEMO",
                                     activity_context=context, created_at=when, started_at=when, fps=25.0, is_test=False)
            db.add(session)
            db.flush()
            db.add(models.ActivitySegment(session_id=session.id, activity_type=context, start_seconds=0, confirmed=True))
            duration_min = simulate_session(db, rng, settings, session, course, room, index, len(contexts))
            add_audio(db, rng, session, course, duration_min, room)
            fuse(db, session.id, settings)
            session.duration = duration_min * 60.0
            session.total_frames = session.processed_frames = int(session.duration * session.fps)
            session.status = session.processing_stage = "COMPLETED"
            session.progress, session.eta_seconds, session.processing_speed = 100, 0, round(rng.uniform(38, 55), 2)
            session.ended_at = when + timedelta(minutes=duration_min)
            db.commit()
            for fmt, factory in (("csv", create_csv_report), ("pdf", create_pdf_report)):
                db.add(models.Report(session_id=session.id, format=fmt, path=str(factory(db, session.id)), created_at=session.ended_at))
            db.commit()
            all_sessions.append(session)
            created += 1
            print(f"  {session.name:<48} {context:<20} {when:%a %d %b %H:%M}")
        if code == "CS101":
            db.add(models.CollaborationNote(scope_type="COURSE", scope_id=course_row.id, author_user_id=users[owner].id, body=NOTES[0][0], review_status=NOTES[0][1]))
        if code == "PHY120":
            db.add(models.CollaborationNote(scope_type="COURSE", scope_id=course_row.id, author_user_id=users["a.okafor@ambisense.demo"].id, body=NOTES[1][0], review_status=NOTES[1][1]))
    exam = next(s for s in all_sessions if s.activity_context == "EXAMINATION")
    db.add(models.CollaborationNote(scope_type="SESSION", scope_id=exam.id, author_user_id=users["a.okafor@ambisense.demo"].id, body=NOTES[2][0], review_status=NOTES[2][1]))
    db.commit()
    notifications = generate_alerts(db, all_sessions, None, settings)
    for email in ("admin@ambisense.demo", "r.iyer@ambisense.demo", "m.chen@ambisense.demo"):
        generate_alerts(db, all_sessions, users[email].id, settings)
    return created, notifications


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="remove previous demo data before seeding")
    parser.add_argument("--remove", action="store_true", help="remove demo data and exit")
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    ensure_session_columns()
    with SessionLocal() as db:
        if args.remove or args.reset:
            print(f"Removed {remove_demo(db)} demo sessions and their classrooms, courses and users.")
            if args.remove:
                return
        elif db.scalar(select(models.Session.id).where(models.Session.job_id.like(f"{JOB_PREFIX}%")).limit(1)):
            print("Demo data already exists. Use --reset to rebuild it or --remove to delete it.")
            return
        print("Seeding demo data (labelled DEMO)...")
        created, notifications = seed(db)
    print(f"\nCreated {created} demo sessions across {len(COURSES)} courses and {len(CLASSROOMS) + 1} classrooms; {notifications} notifications.")
    print(f"Demo accounts (used only when AUTH_ENABLED=true), password {DEMO_PASSWORD}:")
    for email, _, role in USERS:
        print(f"  {role:<14} {email}")


if __name__ == "__main__":
    main()
