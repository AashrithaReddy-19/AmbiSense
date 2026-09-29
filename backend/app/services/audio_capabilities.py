"""Truthful report of which optional audio features can actually run.

Never claims a function is operational unless its adapter is configured *and*
its model/library/binary is present. Speaker labels are anonymous roles.
"""
import importlib.util
import shutil


def audio_capabilities(settings) -> dict:
    ffmpeg = shutil.which("ffmpeg") is not None
    transcription_configured = settings.transcription_provider.upper() != "NONE"
    transcription_available = transcription_configured and importlib.util.find_spec("faster_whisper") is not None
    diarization_configured = settings.diarization_provider.upper() != "NONE"
    # No diarization adapter ships with the project: LOCAL_ADAPTER is an extension point only.
    diarization_available = False
    if not settings.audio_analytics_enabled:
        status, reason = "DISABLED", "Audio analytics is disabled (AUDIO_ANALYTICS_ENABLED=false)."
    elif not ffmpeg:
        status, reason = "MODEL_UNAVAILABLE", "FFmpeg is not installed, so audio cannot be extracted."
    elif not transcription_configured:
        status, reason = "NOT_CONFIGURED", "Audio quality analysis can run, but no transcription provider is configured."
    elif not transcription_available:
        status, reason = "MODEL_UNAVAILABLE", "A transcription provider is configured but its library is not installed."
    else:
        status, reason = "READY", "Audio extraction and transcription are available."
    return {
        "status": status, "reason": reason, "audio_processing_enabled": bool(settings.audio_analytics_enabled), "ffmpeg_available": ffmpeg,
        "transcription": {"configured": transcription_configured, "provider": settings.transcription_provider, "model_available": transcription_available, "model": settings.transcription_model if transcription_configured else None},
        "diarization": {"configured": diarization_configured, "provider": settings.diarization_provider, "model_available": diarization_available, "note": "No diarization model is bundled. Speaker labels are anonymous roles and never identify a person."},
        "identity": "anonymous",
    }
