"""Exercise the real upload pipeline with a supplied video (synthetic is acceptable for mechanics only)."""
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.main import app, settings


def main() -> int:
    video = Path(sys.argv[1]) if len(sys.argv) > 1 else next(Path("videos").glob("*.avi"), None)
    if not video or not video.exists():
        print("Provide a video path.", file=sys.stderr)
        return 2
    settings.demo_mode = False
    with TestClient(app) as client, video.open("rb") as stream:
        response = client.post("/api/videos/upload", files={"file": (video.name, stream, "video/x-msvideo")}, data={"name": "Real pipeline validation"})
        response.raise_for_status()
        session_id = response.json()["id"]
        session = client.get(f"/api/sessions/{session_id}").json()
        timeline = client.get(f"/api/sessions/{session_id}/timeline").json()
        print(json.dumps({"session": session, "snapshots": len(timeline), "real_rows": sum(row["mode"] == "REAL" for row in timeline)}, indent=2))
        if session["status"] != "COMPLETED" or not session["annotated_video_path"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
