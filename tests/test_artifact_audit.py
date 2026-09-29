"""scripts/audit_artifacts.py and backend/app/services/artifact_audit.py: report-only by default, deletion only by explicit
file names with --apply, and never outside the managed directories or for anything a database row references."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from backend.app import models
from backend.app.database import Base
from backend.app.services import artifact_audit as audit_module

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_artifacts.py"
HEX_A, HEX_B, HEX_C, HEX_D = "a" * 32, "b" * 32, "c" * 32, "d" * 32


def _write(path: Path, content: bytes = b"data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture()
def world(tmp_path):
    """A temporary database plus managed directories, with one file of every classification."""
    videos, reports = tmp_path / "videos", tmp_path / "reports"
    videos.mkdir(); reports.mkdir()
    database = tmp_path / "audit.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)

    real_video = _write(videos / f"{HEX_A}.mp4")
    test_annotated = _write(reports / "annotated_2.mp4")
    real_report = _write(reports / "session_1.pdf")
    convention_csv = _write(reports / "session_1.csv")          # no Report row, but session 1 exists
    orphan_upload = _write(videos / f"{HEX_B}.avi", b"orphan upload")
    orphan_report = _write(reports / "session_999.pdf", b"orphan report")  # session 999 does not exist
    orphan_reference = _write(videos / "classroom_references" / f"classroom_1_{HEX_C}.jpg")
    unknown = _write(reports / "notes.txt")
    outside = _write(tmp_path / "outside" / "precious.txt", b"must survive")

    with OrmSession(engine) as db:
        db.add(models.Session(id=1, name="Real lecture", source_type="VIDEO", video_path=str(real_video), status="COMPLETED"))
        db.add(models.Session(id=2, name="Api test fixture", source_type="VIDEO", annotated_video_path=str(test_annotated), status="COMPLETED", is_test=True))
        db.flush()
        db.add(models.Report(session_id=1, format="pdf", path=str(real_report)))
        db.commit()
    engine.dispose()
    return {"tmp": tmp_path, "db": database, "videos": videos, "reports": reports, "roots": [videos, reports, videos / "classroom_references"],
            "real_video": real_video, "test_annotated": test_annotated, "real_report": real_report, "convention_csv": convention_csv,
            "orphan_upload": orphan_upload, "orphan_report": orphan_report, "orphan_reference": orphan_reference, "unknown": unknown, "outside": outside}


def _classified(world):
    result = audit_module.audit(world["db"], world["roots"], ROOT)
    return result, {Path(record.path).name: record for record in result.records}


def _fingerprint(*folders: Path):
    digest = hashlib.sha256()
    for folder in folders:
        for current, _dirs, files in os.walk(folder):
            for name in sorted(files):
                path = Path(current, name)
                digest.update(f"{path}|{path.stat().st_size}|{path.stat().st_mtime_ns}|{path.read_bytes()!r}".encode())
    return digest.hexdigest()


def _cli(world, *extra, database=None):
    url = f"sqlite:///{(database or world['db']).as_posix()}"
    return subprocess.run([sys.executable, str(SCRIPT), "--database-url", url, "--upload-dir", str(world["videos"]), "--report-dir", str(world["reports"]), *extra],
                          capture_output=True, text=True, cwd=ROOT, env={**os.environ, "CLASSROOM_REFERENCE_DIR": str(world["videos"] / "classroom_references")})


def test_every_file_gets_the_right_classification_and_association(world):
    result, by_name = _classified(world)
    real = by_name[world["real_video"].name]
    assert (real.classification, real.session_id, real.referenced, real.in_managed_dir) == (audit_module.REFERENCED_REAL, 1, True, True) and real.reference == "sessions.video_path"
    assert by_name["annotated_2.mp4"].classification == audit_module.REFERENCED_TEST and by_name["annotated_2.mp4"].session_id == 2
    report = by_name["session_1.pdf"]
    assert report.classification == audit_module.REFERENCED_REAL and report.reference == "reports.path" and report.report_id is not None
    convention = by_name["session_1.csv"]
    assert convention.classification == audit_module.REFERENCED_REAL and convention.reference == "generated-name convention"
    for orphan in ("orphan_upload", "orphan_report", "orphan_reference"):
        record = by_name[world[orphan].name]
        assert record.classification == audit_module.UNREFERENCED and not record.referenced and record.session_id is None
    assert by_name["notes.txt"].classification == audit_module.UNKNOWN
    assert all(record.size > 0 and record.modified.endswith("+00:00") for record in result.records)
    assert "precious.txt" not in by_name  # a file outside every managed root is never listed
    assert result.missing_referenced == []


def test_a_row_pointing_at_a_missing_file_is_reported_separately(world):
    world["real_video"].unlink()
    result, by_name = _classified(world)
    assert world["real_video"].name not in by_name
    assert [Path(item["path"]).name.lower() for item in result.missing_referenced] == [world["real_video"].name.lower()]


def test_report_mode_is_byte_for_byte_immutable_for_files_and_database(world):
    before_files = _fingerprint(world["videos"], world["reports"], world["outside"].parent)
    before_db = hashlib.sha256(world["db"].read_bytes()).hexdigest()
    table = _cli(world)
    as_json = _cli(world, "--json")
    only = _cli(world, "--only", "UNREFERENCED")
    for result in (table, as_json, only):
        assert result.returncode == 0, result.stderr
    assert "Nothing was changed" in table.stdout
    payload = json.loads(as_json.stdout[as_json.stdout.index("{"):])
    assert payload["summary"]["by_classification"]["UNREFERENCED"]["files"] == 3
    assert payload["summary"]["by_classification"]["UNKNOWN"]["files"] == 1
    assert _fingerprint(world["videos"], world["reports"], world["outside"].parent) == before_files
    assert hashlib.sha256(world["db"].read_bytes()).hexdigest() == before_db


def test_delete_without_apply_is_a_preview_and_removes_nothing(world):
    result = _cli(world, "--delete", str(world["orphan_upload"]))
    assert result.returncode == 0 and "WOULD DELETE" in result.stdout and "Nothing was changed" in result.stdout
    assert world["orphan_upload"].exists()


def test_apply_deletes_exactly_the_named_unreferenced_file_and_is_idempotent(world):
    neighbours = [world[name] for name in ("orphan_report", "orphan_reference", "real_video", "real_report", "unknown", "test_annotated")]
    result = _cli(world, "--delete", str(world["orphan_upload"]), "--apply")
    assert result.returncode == 0 and "DELETED" in result.stdout
    assert not world["orphan_upload"].exists()
    assert all(path.exists() for path in neighbours)          # nothing else was touched
    again = _cli(world, "--delete", str(world["orphan_upload"]), "--apply")
    assert again.returncode == 1 and "Refused" in again.stdout  # already gone: refused, not an error crash


def test_referenced_and_unknown_files_are_refused_even_with_apply(world):
    for key in ("real_video", "real_report", "test_annotated", "convention_csv", "unknown"):
        result = _cli(world, "--delete", str(world[key]), "--apply")
        assert result.returncode == 1 and "Refused" in result.stdout, key
        assert world[key].exists(), key


def test_path_traversal_outside_roots_directories_wildcards_and_symlinks_are_refused(world):
    result, _ = _classified(world)
    roots = world["roots"]
    traversal = str(world["reports"] / ".." / "outside" / "precious.txt")
    plan = audit_module.plan_deletion([traversal, str(world["outside"]), str(world["reports"]), str(world["videos"] / "classroom_references"), str(world["reports"] / "*.pdf"),
                                       str(world["videos"] / "does_not_exist.avi")], result, roots)
    assert [entry["allowed"] for entry in plan] == [False] * 6
    reasons = " | ".join(entry["reason"] for entry in plan)
    assert "outside the managed" in reasons and "directories are never deleted" in reasons and "Wildcards" in reasons and "not an existing regular file" in reasons
    assert world["outside"].read_bytes() == b"must survive" and world["reports"].is_dir()

    cli = _cli(world, "--delete", traversal, "--apply")
    assert cli.returncode == 1 and world["outside"].exists()

    link = world["reports"] / "link_to_outside.txt"
    try:
        link.symlink_to(world["outside"])
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available on this account")
    result_with_link, by_name = _classified(world)
    assert by_name["link_to_outside.txt"].classification == audit_module.UNKNOWN
    link_plan = audit_module.plan_deletion([str(link)], result_with_link, roots)
    assert link_plan[0]["allowed"] is False and "symbolic link" in link_plan[0]["reason"]
    assert world["outside"].exists()


def test_a_symlinked_directory_is_not_walked(world):
    target = world["tmp"] / "elsewhere"
    _write(target / f"{HEX_D}.mp4")
    link = world["reports"] / "linked_dir"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available on this account")
    _, by_name = _classified(world)
    assert f"{HEX_D}.mp4" not in by_name


def test_cli_refuses_bad_invocations_and_environments_safely(world, tmp_path):
    assert _cli(world, "--apply").returncode == 2                     # --apply alone is meaningless
    missing = _cli(world, database=tmp_path / "nope.db")
    assert missing.returncode == 2 and "not found" in missing.stdout and not (tmp_path / "nope.db").exists()
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not a database" * 50)
    unreadable = _cli(world, database=garbage)
    assert unreadable.returncode == 2 and "Nothing was changed" in unreadable.stdout
    other = subprocess.run([sys.executable, str(SCRIPT), "--database-url", "postgresql://user:secret@host/db"], capture_output=True, text=True, cwd=ROOT)
    assert other.returncode == 2 and "only supports SQLite" in other.stdout and "secret" not in other.stdout + other.stderr


def test_symlink_handling_without_needing_symlink_privileges(world, monkeypatch):
    """Simulate a symlink by patching Path.is_symlink, so the refusal logic is covered even where links cannot be created."""
    target = world["orphan_upload"]
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == target.name or real_is_symlink(self))
    result, by_name = _classified(world)
    assert by_name[target.name].classification == audit_module.UNKNOWN and "symbolic link" in by_name[target.name].note
    plan = audit_module.plan_deletion([str(target)], result, world["roots"])
    assert plan[0]["allowed"] is False and "symbolic link" in plan[0]["reason"]
    assert audit_module.delete_selected(plan)[0]["deleted"] is False and target.exists()
