"""scripts/quarantine_artifacts.py: only PROVEN automated-test artifacts move, nothing is deleted, the move is reversible, and the
default is a dry run that changes nothing."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from backend.app import models
from backend.app.database import Base
from backend.app.services import artifact_audit as audit_module

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "quarantine_artifacts.py"
HEX = {key: key * 32 for key in "abcdef"}


def _write(path: Path, content: bytes = b"data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _clip(path: Path, noisy: bool = False, size=(160, 90), frames=15) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5, size)
    rng = np.random.default_rng(7)
    for index in range(frames):
        frame = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8) if noisy else np.full((size[1], size[0], 3), 20 + index * 3, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture()
def world(tmp_path):
    """A project-shaped folder (videos/, reports/, backups/) with a database and one file of every kind."""
    project = tmp_path / "project"
    videos, reports = project / "videos", project / "reports"
    videos.mkdir(parents=True); reports.mkdir(); (project / "backups").mkdir()
    database = project / "audit.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)

    real_video = _write(videos / f"{HEX['a']}.mp4", b"real footage would be much larger" * 50)
    synthetic = _clip(videos / f"{HEX['b']}.avi")                                   # proven: tiny, uniform
    natural = _clip(videos / f"{HEX['c']}.avi", noisy=True)                         # unreferenced but NOT uniform: not proven
    large = _clip(videos / f"{HEX['d']}.avi", size=(640, 360), frames=10)          # unreferenced, uniform but not tiny: not proven
    test_report = _write(reports / "session_900.pdf", b"test report")               # session 900 deleted by a cleanup run, name "API test": proven
    real_named_report = _write(reports / "session_901.pdf", b"a real deleted session")  # 901 deleted, but recorded name is not a test fixture: not proven
    not_recorded = _write(reports / "session_902.pdf", b"no deletion record")       # no record at all: not proven
    referenced = _write(reports / "session_1.pdf", b"real report")                  # referenced by a report row: never touched
    unknown = _write(reports / "notes.txt", b"unknown")
    outside = _write(tmp_path / "outside" / "precious.txt", b"must survive")

    with OrmSession(engine) as db:
        db.add(models.Session(id=1, name="Real lecture", source_type="VIDEO", video_path=str(real_video), status="COMPLETED"))
        db.flush()
        db.add(models.Report(session_id=1, format="pdf", path=str(referenced)))
        db.add(models.CleanupAudit(run_id="run-test", session_id=900, action="DELETE", result="CHANGED", details={"name": "API test", "cutoff": "2026-01-01T00:00:00"}))
        db.add(models.CleanupAudit(run_id="run-real", session_id=901, action="DELETE", result="CHANGED", details={"name": "Quarterly physics lecture", "cutoff": "2026-01-01T00:00:00"}))
        db.commit()
    engine.dispose()
    return {"project": project, "db": database, "roots": [videos, reports, videos / "classroom_references"], "videos": videos, "reports": reports,
            "synthetic": synthetic, "natural": natural, "large": large, "test_report": test_report, "real_named_report": real_named_report, "not_recorded": not_recorded,
            "referenced": referenced, "real_video": real_video, "unknown": unknown, "outside": outside}


def _proposal(world):
    result = audit_module.audit(world["db"], world["roots"], world["project"])
    proven, left = audit_module.find_proven_test_artifacts(result, world["db"])
    return result, proven, left


def _tree(*folders):
    digest = hashlib.sha256()
    for folder in folders:
        for current, _dirs, files in os.walk(folder):
            for name in sorted(files):
                path = Path(current, name)
                digest.update(f"{path}|{path.stat().st_size}|{path.stat().st_mtime_ns}|{hashlib.sha256(path.read_bytes()).hexdigest()}".encode())
    return digest.hexdigest()


def _cli(world, *extra):
    env = {**os.environ, "CLASSROOM_REFERENCE_DIR": str(world["videos"] / "classroom_references")}
    return subprocess.run([sys.executable, str(SCRIPT), "--database-url", f"sqlite:///{world['db'].as_posix()}", "--upload-dir", str(world["videos"]), "--report-dir", str(world["reports"]), "--project-root", str(world["project"]), *extra],
                          capture_output=True, text=True, cwd=ROOT, env=env)


def test_only_proven_test_artifacts_are_proposed(world):
    _, proven, left = _proposal(world)
    proposed = {Path(item["record"].path).name for item in proven}
    assert proposed == {world["synthetic"].name, world["test_report"].name}
    by_name = {Path(item["record"].path).name: item for item in proven}
    assert by_name["session_900.pdf"]["evidence"]["recorded_name"] == "API test" and by_name["session_900.pdf"]["evidence"]["cleanup_run_id"] == "run-test"
    assert "160x90, 15 frames" in by_name[world["synthetic"].name]["evidence"]["decoded"]
    left_names = {Path(record.path).name for record in left}
    assert {world["natural"].name, world["large"].name, "session_901.pdf", "session_902.pdf"} <= left_names   # unreferenced, but not proven
    assert world["referenced"].name not in proposed | left_names and world["real_video"].name not in proposed | left_names and "notes.txt" not in proposed | left_names


def test_dry_run_changes_nothing(world):
    before = _tree(world["project"] / "videos", world["project"] / "reports", world["outside"].parent)
    db_before = hashlib.sha256(world["db"].read_bytes()).hexdigest()
    result = _cli(world)
    assert result.returncode == 0 and "Dry run: nothing was changed" in result.stdout and "Proposed move: 2 file(s)" in result.stdout
    assert _tree(world["project"] / "videos", world["project"] / "reports", world["outside"].parent) == before
    assert hashlib.sha256(world["db"].read_bytes()).hexdigest() == db_before
    assert not list((world["project"] / "backups").iterdir())      # no quarantine folder was even created


def test_apply_moves_only_proven_files_writes_a_manifest_and_deletes_nothing(world):
    kept = [world[key] for key in ("natural", "large", "real_named_report", "not_recorded", "referenced", "real_video", "unknown", "outside")]
    kept_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in kept}
    moved_hashes = {world[key]: hashlib.sha256(world[key].read_bytes()).hexdigest() for key in ("synthetic", "test_report")}
    destination = world["project"] / "backups" / "quarantine_test"
    result = _cli(world, "--apply", "--quarantine-dir", str(destination))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Restore with:" in result.stdout
    for path, digest in kept_hashes.items():
        assert path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest, path.name    # untouched
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["moved"] == 2 and manifest["skipped"] == [] and all(entry["verified_after_move"] for entry in manifest["entries"])
    for path, digest in moved_hashes.items():
        assert not path.exists()
        held = destination / path.relative_to(world["project"])
        assert held.is_file() and hashlib.sha256(held.read_bytes()).hexdigest() == digest        # moved intact, not deleted
    entry = next(e for e in manifest["entries"] if e["original"] == "reports/session_900.pdf")
    assert entry["sha256"] and entry["size"] == len(b"test report") and entry["evidence"]["recorded_name"] == "API test" and entry["modified"].endswith("+00:00")
    again = _cli(world, "--apply", "--quarantine-dir", str(world["project"] / "backups" / "quarantine_second"))
    assert "Proposed move: 0 file(s)" in again.stdout                                              # idempotent: nothing left to prove


def test_restore_round_trip_refuses_overwrites_and_tampering(world):
    destination = world["project"] / "backups" / "quarantine_rt"
    assert _cli(world, "--apply", "--quarantine-dir", str(destination)).returncode == 0
    manifest = destination / "manifest.json"
    preview = _cli(world, "--restore", str(manifest))
    assert preview.returncode == 0 and "Dry run" in preview.stdout and not world["test_report"].exists()
    # something already lives at one original path -> that one is refused, the other is restored
    _write(world["test_report"], b"a newer file")
    partial = _cli(world, "--restore", str(manifest), "--apply")
    assert partial.returncode == 1 and "something already exists" in partial.stdout.lower()
    assert world["test_report"].read_bytes() == b"a newer file" and world["synthetic"].exists()
    # a tampered quarantined file is refused
    world["test_report"].unlink()
    held = destination / "reports" / "session_900.pdf"
    held.write_bytes(b"tampered")
    tampered = _cli(world, "--restore", str(manifest), "--apply")
    assert tampered.returncode == 1 and "checksum differs" in tampered.stdout.lower() and not world["test_report"].exists()
    held.write_bytes(b"test report")
    final = _cli(world, "--restore", str(manifest), "--apply")
    assert world["test_report"].read_bytes() == b"test report" and "1 restored, 1 refused" in final.stdout   # the clip was already restored earlier: refused, not overwritten
    assert final.returncode == 1 and world["synthetic"].exists()


def test_a_manifest_cannot_restore_outside_the_managed_folders(world, tmp_path):
    destination = world["project"] / "backups" / "quarantine_evil"
    destination.mkdir(parents=True)
    payload = _write(destination / "payload.txt", b"payload")
    evil = {"created": "x", "project_root": str(world["project"]), "database": "audit.db", "skipped": [], "entries": [
        {"original": "../outside/planted.txt", "quarantine": "payload.txt", "size": 7, "modified": "x", "sha256": hashlib.sha256(b"payload").hexdigest(), "reason": "x", "evidence": {}},
        {"original": "backups/elsewhere.txt", "quarantine": "payload.txt", "size": 7, "modified": "x", "sha256": hashlib.sha256(b"payload").hexdigest(), "reason": "x", "evidence": {}}]}
    (destination / "manifest.json").write_text(json.dumps(evil), encoding="utf-8")
    result = _cli(world, "--restore", str(destination / "manifest.json"), "--apply")
    assert result.returncode == 1 and result.stdout.lower().count("outside the managed directories") == 2
    assert not (world["outside"].parent / "planted.txt").exists() and not (world["project"] / "backups" / "elsewhere.txt").exists() and payload.exists()


def test_symlinks_and_files_that_became_referenced_are_never_moved(world, monkeypatch):
    result, proven, _ = _proposal(world)
    target = next(item for item in proven if Path(item["record"].path).name == "session_900.pdf")
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "session_900.pdf" or real_is_symlink(self))
    manifest = audit_module.quarantine([target], world["project"] / "backups" / "q_symlink", world["project"], world["roots"], "audit.db")
    assert manifest["moved"] == 0 and manifest["skipped"] and world["test_report"].exists()


def test_cli_refuses_missing_database_and_non_sqlite_and_a_quarantine_inside_managed_folders(world, tmp_path):
    missing = subprocess.run([sys.executable, str(SCRIPT), "--database-url", f"sqlite:///{(tmp_path / 'nope.db').as_posix()}"], capture_output=True, text=True, cwd=ROOT)
    assert missing.returncode == 2 and "not found" in missing.stdout and not (tmp_path / "nope.db").exists()
    other = subprocess.run([sys.executable, str(SCRIPT), "--database-url", "postgresql://user:secret@host/db"], capture_output=True, text=True, cwd=ROOT)
    assert other.returncode == 2 and "only supports SQLite" in other.stdout and "secret" not in other.stdout + other.stderr
    inside = _cli(world, "--apply", "--quarantine-dir", str(world["reports"] / "quarantine_inside"))
    assert inside.returncode == 2 and "outside the managed" in inside.stdout and world["test_report"].exists()
