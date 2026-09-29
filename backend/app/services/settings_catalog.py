"""Catalogue of the settings the application really supports.

Each entry lists its group, unit, allowed range/choices, whether changing it
needs a restart, and whether it is *runtime-editable*. Environment-controlled
values (paths, secrets, limits that are read once at startup) are read-only in
the UI. Secrets are never included: ``auth_secret_key`` and ``redis_url`` are
deliberately absent from the catalogue and from every response.
"""
from .audio_capabilities import audio_capabilities

GROUPS = ["General", "Analytics", "Models", "Thresholds", "Privacy & Retention", "Reports", "Optional Audio", "Feature Flags", "System"]


def _entry(key, group, label, unit=None, minimum=None, maximum=None, choices=None, editable=True, restart=False, risky=False, description="", kind="number"):
    return {"key": key, "group": group, "label": label, "kind": kind, "unit": unit, "min": minimum, "max": maximum, "choices": choices, "editable": editable, "restart_required": restart, "risky": risky, "description": description}


CATALOG = [
    _entry("expected_students", "General", "Expected students", "people", 1, 500, description="Used to estimate occupancy against expected attendance capacity."),
    _entry("total_seats", "General", "Total seats", "seats", 1, 500, description="Room capacity used for the unoccupied-capacity estimate."),
    _entry("process_every_n_frames", "Analytics", "Process every N frames", "frames", 1, 30, description="Higher values are faster but sample less evidence."),
    _entry("aggregation_interval", "Analytics", "Aggregation interval", "seconds", 1, 60, risky=True, description="Changes how evidence is bucketed for new processing jobs."),
    _entry("ema_alpha", "Analytics", "Smoothing factor (EMA α)", "0–1", 0.01, 1, risky=True, description="Weight of new samples in exponential smoothing."),
    _entry("yolo_confidence", "Models", "Detector confidence", "0–1", 0.05, 1, risky=True, description="Minimum person-detection confidence."),
    _entry("tracking_confidence", "Models", "Tracker confidence", "0–1", 0.05, 1, risky=True, description="Minimum confidence to keep an anonymous track."),
    _entry("ear_threshold", "Thresholds", "Eye-aspect-ratio threshold", "ratio", 0.05, 0.6, risky=True, description="Below this an eye is treated as closed (possible prolonged eye closure)."),
    _entry("drowsiness_duration", "Thresholds", "Prolonged eye-closure duration", "seconds", 0.1, 20, risky=True),
    _entry("yawn_threshold", "Thresholds", "Mouth-aspect-ratio threshold", "ratio", 0.1, 2, risky=True),
    _entry("yawn_min_duration", "Thresholds", "Minimum yawn duration", "seconds", 0.1, 20, risky=True),
    _entry("head_yaw_threshold", "Thresholds", "Head yaw threshold", "degrees", 1, 90, risky=True, description="Visual-orientation estimate; not attention."),
    _entry("head_pitch_threshold", "Thresholds", "Head pitch threshold", "degrees", 1, 90, risky=True),
    _entry("distraction_min_duration", "Thresholds", "Minimum off-forward orientation duration", "seconds", 0.5, 60, risky=True),
    _entry("privacy_mode", "Privacy & Retention", "Privacy mode", kind="boolean", risky=True, description="Keeps tracking anonymous and session-local. Turning it off is not recommended."),
    _entry("show_overlays", "Reports", "Show overlays on annotated video", kind="boolean"),
    _entry("retention_days", "Privacy & Retention", "Session retention period", "days", 1, 3650, risky=True, description="Sessions older than this are offered for archiving (never deleted automatically)."),
    _entry("transcript_retention_enabled", "Privacy & Retention", "Transcript retention enabled", kind="boolean", risky=True),
    _entry("transcript_retention_days", "Privacy & Retention", "Transcript retention period", "days", 1, 3650, risky=True),
    _entry("audio_analytics_enabled", "Optional Audio", "Audio analytics enabled", kind="boolean", description="Optional; requires FFmpeg. Disabled by default."),
    _entry("transcription_provider", "Optional Audio", "Transcription provider", kind="choice", choices=["NONE", "FASTER_WHISPER"], risky=True),
    _entry("transcription_model", "Optional Audio", "Transcription model", kind="text"),
    _entry("transcription_language", "Optional Audio", "Transcription language", kind="text"),
    _entry("diarization_provider", "Optional Audio", "Diarization provider", kind="choice", choices=["NONE", "LOCAL_ADAPTER"], description="Speakers are anonymous labels; identities are never inferred."),
    _entry("demo_mode", "Feature Flags", "Demo mode", kind="boolean", risky=True, description="Generates synthetic DEMO data. Never mix with real evidence."),
]
# Read-only, environment-controlled values shown for transparency (no secrets, no paths).
READ_ONLY = [
    ("max_upload_mb", "Reports", "Maximum upload size", "MB"), ("max_video_duration_minutes", "Reports", "Maximum video duration", "minutes"),
    ("yolo_model", "Models", "Detector model", None), ("log_level", "System", "Log level", None), ("auth_enabled", "System", "Authentication enabled", None),
    ("auth_mode", "System", "Authentication mode", None), ("job_runner_mode", "System", "Job runner", None), ("rate_limit_enabled", "System", "Rate limiting enabled", None),
    ("rate_limit_backend", "System", "Rate-limit backend", None), ("scheduled_cleanup_enabled", "Privacy & Retention", "Scheduled cleanup enabled", None), ("test_session_cleanup_enabled", "Privacy & Retention", "Test-session cleanup enabled", None),
    ("test_session_cleanup_action", "Privacy & Retention", "Test-session cleanup action", None), ("test_session_cleanup_age_hours", "Privacy & Retention", "Test-session cleanup age", "hours"),
    ("minimum_metric_coverage", "Analytics", "Minimum metric coverage", "0–1"),
]
ENV_ONLY_SETTINGS = {key for key, *_ in READ_ONLY}


def settings_catalog(settings) -> dict:
    entries = []
    for entry in CATALOG:
        entries.append({**entry, "value": getattr(settings, entry["key"])})
    for key, group, label, unit in READ_ONLY:
        value = getattr(settings, key)
        entries.append({**_entry(key, group, label, unit, editable=False, restart=True, kind="readonly"), "value": value if not hasattr(value, "as_posix") else getattr(value, "name", str(value)), "source": "environment"})
    return {"groups": GROUPS, "settings": entries, "audio": audio_capabilities(settings), "notice": "Threshold changes apply to new processing jobs only and never alter stored evidence."}
