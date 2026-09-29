"""Read-only audit of files in the managed artifact directories (uploads, reports, classroom references).

The audit answers one question per file: does anything in the database point at it? It never modifies the database
(the connection is opened read-only) and never touches a file. Deleting is a separate, explicit step
(`plan_deletion` / `delete_selected`) that only ever removes individually named regular files that sit inside a managed
root and are classified UNREFERENCED - never directories, never symlinks, never anything a database row references.
"""
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REFERENCED_REAL = "REFERENCED_REAL"
REFERENCED_TEST = "REFERENCED_TEST"
UNREFERENCED = "UNREFERENCED"
UNKNOWN = "UNKNOWN"
CLASSIFICATIONS = (REFERENCED_REAL, REFERENCED_TEST, UNREFERENCED, UNKNOWN)

_VIDEO_EXTENSIONS = {".avi", ".mkv", ".mov", ".mp4"}
_CLASSROOM_REFERENCE = re.compile(r"^classroom_\d+_[0-9a-f]{32}\.(?:jpg|jpeg|png)$", re.IGNORECASE)
_UPLOAD_NAME = re.compile(r"^[0-9a-f]{32}$")  # uploads are stored under a random hex name
# Names the application itself generates for a session, with the session id captured.
_SESSION_NAME_PATTERNS = (
    re.compile(r"^annotated_live_(\d+)\.mp4$"), re.compile(r"^annotated_(\d+)\.mp4$"),
    re.compile(r"^session_(\d+)_metrics\.csv$"), re.compile(r"^session_(\d+)\.(?:csv|pdf)$"),
    re.compile(r"^audio_(\d+)\.wav$"), re.compile(r"^transcript_(\d+)\.(?:json|csv|txt)$"),
)


@dataclass
class ArtifactRecord:
    path: str
    size: int
    modified: str
    in_managed_dir: bool
    referenced: bool
    reference: str | None
    session_id: int | None
    report_id: int | None
    classification: str
    note: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class AuditResult:
    records: list[ArtifactRecord] = field(default_factory=list)
    missing_referenced: list[dict] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        counts = {name: {"files": 0, "bytes": 0} for name in CLASSIFICATIONS}
        for record in self.records:
            counts[record.classification]["files"] += 1
            counts[record.classification]["bytes"] += record.size
        return {"files": len(self.records), "by_classification": counts, "referenced_but_missing": len(self.missing_referenced)}


def _key(path: Path) -> str:
    return os.path.normcase(str(path))


def _resolved(value: str, base_dir: Path) -> Path | None:
    try:
        path = Path(value)
        return (path if path.is_absolute() else base_dir / path).resolve()
    except (OSError, ValueError):
        return None


def _connect_readonly(database: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _load_references(connection: sqlite3.Connection, base_dir: Path) -> tuple[dict[str, dict], dict[int, dict]]:
    """Map normalised absolute path -> {reference, session_id, report_id}; and session id -> {name, is_test}."""
    sessions: dict[int, dict] = {}
    references: dict[str, dict] = {}
    session_columns = _columns(connection, "sessions")
    if "id" in session_columns:
        wanted = [c for c in ("id", "name", "is_test", "video_path", "annotated_video_path") if c in session_columns]
        for row in connection.execute(f"SELECT {', '.join(wanted)} FROM sessions"):
            record = dict(zip(wanted, row))
            sessions[record["id"]] = {"name": record.get("name"), "is_test": bool(record.get("is_test"))}
            for column in ("video_path", "annotated_video_path"):
                if record.get(column):
                    path = _resolved(record[column], base_dir)
                    if path:
                        references.setdefault(_key(path), {"reference": f"sessions.{column}", "session_id": record["id"], "report_id": None})
    report_columns = _columns(connection, "reports")
    if {"id", "session_id", "path"} <= report_columns:
        for report_id, session_id, value in connection.execute("SELECT id, session_id, path FROM reports"):
            path = _resolved(value, base_dir) if value else None
            if path:
                references.setdefault(_key(path), {"reference": "reports.path", "session_id": session_id, "report_id": report_id})
    audio_columns = _columns(connection, "audio_analyses")
    if {"session_id", "audio_path"} <= audio_columns:
        for session_id, value in connection.execute("SELECT session_id, audio_path FROM audio_analyses WHERE audio_path IS NOT NULL"):
            path = _resolved(value, base_dir)
            if path:
                references.setdefault(_key(path), {"reference": "audio_analyses.audio_path", "session_id": session_id, "report_id": None})
    for table in ("classrooms", "classroom_layouts"):
        if {"id", "reference_image_path"} <= _columns(connection, table):
            for row_id, value in connection.execute(f"SELECT id, reference_image_path FROM {table} WHERE reference_image_path IS NOT NULL"):
                path = _resolved(value, base_dir)
                if path:
                    references.setdefault(_key(path), {"reference": f"{table}.reference_image_path (row {row_id})", "session_id": None, "report_id": None})
    return references, sessions


def _within(path: Path, roots: list[Path]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _classify(path: Path, name: str, references: dict, sessions: dict, in_managed: bool) -> tuple[str, dict | None, int | None, str]:
    direct = references.get(_key(path))
    if direct:
        session = sessions.get(direct["session_id"]) if direct["session_id"] is not None else None
        is_test = bool(session and session["is_test"])
        return (REFERENCED_TEST if is_test else REFERENCED_REAL), direct, direct["session_id"], "A database row stores this exact path."
    for pattern in _SESSION_NAME_PATTERNS:
        match = pattern.match(name)
        if match:
            session_id = int(match.group(1))
            session = sessions.get(session_id)
            if session:
                convention = {"reference": "generated-name convention", "session_id": session_id, "report_id": None}
                return (REFERENCED_TEST if session["is_test"] else REFERENCED_REAL), convention, session_id, "Named for an existing session; deleting that session would remove it."
            return UNREFERENCED, None, None, f"Named for session {session_id}, which no longer exists."
    if _CLASSROOM_REFERENCE.match(name):
        return UNREFERENCED, None, None, "A classroom reference image that no classroom or layout row points at (for example, replaced by a newer upload)."
    stem, extension = os.path.splitext(name)
    if _UPLOAD_NAME.match(stem) and extension.lower() in _VIDEO_EXTENSIONS:
        return UNREFERENCED, None, None, "An uploaded video that no session row points at."
    if not in_managed:
        return UNKNOWN, None, None, "Outside the managed artifact directories."
    return UNKNOWN, None, None, "Does not match any file name the application generates; not classified as removable."


def audit(database: Path, roots: list[Path], base_dir: Path) -> AuditResult:
    """Walk each root (no symlink following, no writes) and classify every file. The database is opened read-only."""
    resolved_roots = []
    for root in roots:
        resolved = Path(root).resolve()
        if resolved not in resolved_roots:
            resolved_roots.append(resolved)
    connection = _connect_readonly(database)
    try:
        references, sessions = _load_references(connection, base_dir)
    finally:
        connection.close()
    result = AuditResult(roots=[str(root) for root in resolved_roots])
    seen: set[str] = set()
    for root in resolved_roots:
        if not root.is_dir():
            continue
        for current, directories, files in os.walk(root, followlinks=False):
            directories[:] = sorted(d for d in directories if not Path(current, d).is_symlink())
            for name in sorted(files):
                candidate = Path(current, name)
                key = _key(candidate)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    info = candidate.lstat()
                except OSError:
                    continue
                if candidate.is_symlink():
                    result.records.append(ArtifactRecord(str(candidate), info.st_size, _stamp(info.st_mtime), _within(candidate.parent.resolve(), resolved_roots), False, None, None, None, UNKNOWN, "A symbolic link; never followed or removed."))
                    continue
                in_managed = _within(candidate.resolve(), resolved_roots)
                classification, reference, session_id, note = _classify(candidate.resolve(), name, references, sessions, in_managed)
                result.records.append(ArtifactRecord(str(candidate), info.st_size, _stamp(info.st_mtime), in_managed, reference is not None, reference["reference"] if reference else None,
                                                     session_id, reference["report_id"] if reference else None, classification, note))
    on_disk = {_key(Path(record.path).resolve()) for record in result.records}
    for key, reference in references.items():
        if key not in on_disk and _within(Path(key), [Path(os.path.normcase(str(r))) for r in resolved_roots]):
            result.missing_referenced.append({"path": key, **reference})
    return result


def _stamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def plan_deletion(selection: list[str], result: AuditResult, roots: list[Path]) -> list[dict]:
    """Decide, per explicitly named path, whether it may be deleted. Pure: touches nothing.

    Allowed only if the path is a regular file (not a directory, not a symlink), resolves inside a managed root, was seen by
    the audit, and is classified UNREFERENCED. Wildcards are not expanded and directories are never recursed into."""
    resolved_roots = [Path(root).resolve() for root in roots]
    by_path = {_key(Path(record.path).resolve()): record for record in result.records}
    plan = []
    for raw in selection:
        entry = {"requested": raw, "allowed": False, "reason": "", "path": None, "size": 0}
        if any(character in raw for character in "*?[]"):
            entry["reason"] = "Wildcards are not expanded; name each file explicitly."
            plan.append(entry); continue
        try:
            candidate = Path(raw)
            if candidate.is_symlink():
                entry["reason"] = "Refused: a symbolic link."
                plan.append(entry); continue
            resolved = candidate.resolve()
        except (OSError, ValueError):
            entry["reason"] = "Refused: the path could not be resolved."
            plan.append(entry); continue
        entry["path"] = str(resolved)
        if not _within(resolved, resolved_roots):
            entry["reason"] = "Refused: outside the managed artifact directories."
        elif resolved.is_dir():
            entry["reason"] = "Refused: directories are never deleted."
        elif not resolved.is_file():
            entry["reason"] = "Refused: not an existing regular file."
        else:
            record = by_path.get(_key(resolved))
            entry["size"] = resolved.stat().st_size
            if record is None:
                entry["reason"] = "Refused: the audit did not classify this file."
            elif record.classification != UNREFERENCED:
                entry["reason"] = f"Refused: classified {record.classification}, not UNREFERENCED."
            else:
                entry["allowed"] = True
                entry["reason"] = record.note
        plan.append(entry)
    return plan


def delete_selected(plan: list[dict]) -> list[dict]:
    """Delete exactly the files a plan allows, one `unlink` each. Returns the plan annotated with the outcome."""
    outcome = []
    for entry in plan:
        entry = dict(entry)
        entry["deleted"] = False
        if entry["allowed"]:
            try:
                Path(entry["path"]).unlink()
                entry["deleted"] = True
            except OSError as error:
                entry["reason"] = f"Could not delete ({type(error).__name__})."
        outcome.append(entry)
    return outcome


# ---------------------------------------------------------------------------------------------------------------------------------------
# Quarantine: move *proven* automated-test artifacts aside (never delete), with a manifest that makes the move reversible.
#
# A file is proven only if it is UNREFERENCED by the audit AND one of these holds:
#   1. It is named for a session id that a recorded cleanup run deleted (cleanup_audits DELETE/CHANGED), and the recorded session
#      name is an automated-test fixture name ("API test", "Acceptance session", "Priority 3 ...", ...). The session no longer exists.
#   2. It is an uploaded video (random hex name) that decodes as a tiny synthetic clip: at most 320x240, at most 90 frames and
#      near-uniform frames (the tests generate a few solid-colour frames; real classroom footage never looks like that).
# Everything else - including every file the audit calls UNKNOWN - is left exactly where it is.
# ---------------------------------------------------------------------------------------------------------------------------------------
import hashlib  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402

TEST_SESSION_NAME = re.compile(r"^(api test|acceptance|websocket schema test|old api test cleanup|priority \d|p4 |reference capture api test)", re.IGNORECASE)


def deleted_test_sessions(database: Path) -> dict[int, dict]:
    """session_id -> {name, run_id} for sessions that recorded cleanup runs deleted, restricted to automated-test fixture names."""
    connection = _connect_readonly(database)
    try:
        if "details" not in _columns(connection, "cleanup_audits"):
            return {}
        found = {}
        for run_id, session_id, details in connection.execute("SELECT run_id, session_id, details FROM cleanup_audits WHERE action='DELETE' AND result='CHANGED' AND session_id IS NOT NULL"):
            try:
                name = (json.loads(details) if isinstance(details, str) else details or {}).get("name", "")
            except (TypeError, ValueError):
                continue
            if TEST_SESSION_NAME.match(name or ""):
                found[int(session_id)] = {"name": name, "run_id": run_id}
        return found
    finally:
        connection.close()


def is_synthetic_clip(path: Path) -> tuple[bool, str]:
    """True only for a tiny, near-uniform clip of the kind the automated tests generate. Needs OpenCV; without it nothing is proven."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False, "OpenCV unavailable, so the clip cannot be proven synthetic"
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            return False, "not decodable"
        width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if width > 320 or height > 240 or frames > 90 or frames < 1:
            return False, f"{width}x{height}, {frames} frames is not a tiny synthetic clip"
        spreads = []
        for _ in range(min(frames, 6)):
            ok, frame = capture.read()
            if not ok:
                break
            spreads.append(float(np.std(frame)))
        if not spreads or max(spreads) > 12.0:
            return False, "frames are not near-uniform"
        return True, f"{width}x{height}, {frames} frames, near-uniform (max frame spread {max(spreads):.1f})"
    finally:
        capture.release()


def find_proven_test_artifacts(result: AuditResult, database: Path) -> tuple[list[dict], list[ArtifactRecord]]:
    """(proven, left_alone). `left_alone` is every UNREFERENCED record that could not be proven."""
    deleted = deleted_test_sessions(database)
    proven, left = [], []
    for record in result.records:
        if record.classification != UNREFERENCED:
            continue
        name = Path(record.path).name
        reason = evidence = None
        for pattern in _SESSION_NAME_PATTERNS:
            match = pattern.match(name)
            if match and int(match.group(1)) in deleted:
                info = deleted[int(match.group(1))]
                reason = "session deleted by a recorded cleanup run; the recorded name is an automated-test fixture"
                evidence = {"session_id": int(match.group(1)), "recorded_name": info["name"], "cleanup_run_id": info["run_id"]}
                break
        if reason is None and _UPLOAD_NAME.match(os.path.splitext(name)[0]) and os.path.splitext(name)[1].lower() in _VIDEO_EXTENSIONS:
            synthetic, detail = is_synthetic_clip(Path(record.path))
            if synthetic:
                reason, evidence = "unreferenced upload that decodes as a tiny synthetic test clip", {"decoded": detail}
        if reason:
            proven.append({"record": record, "reason": reason, "evidence": evidence})
        else:
            left.append(record)
    return proven, left


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def quarantine(proven: list[dict], quarantine_dir: Path, project_root: Path, roots: list[Path], database_name: str) -> dict:
    """Move each proven file (one `shutil.move` each, same volume) into `quarantine_dir`, keeping its path relative to the project
    root, and write manifest.json. The manifest is rewritten after every move so an interruption still leaves a usable record."""
    resolved_roots = [Path(root).resolve() for root in roots]
    project_root = Path(project_root).resolve()
    quarantine_dir = Path(quarantine_dir).resolve()
    quarantine_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "project_root": str(project_root), "database": database_name, "entries": [], "skipped": []}
    manifest_path = quarantine_dir / "manifest.json"
    for item in proven:
        source = Path(item["record"].path)
        try:
            resolved = source.resolve()
            if source.is_symlink() or not resolved.is_file() or not _within(resolved, resolved_roots):
                manifest["skipped"].append({"path": str(source), "why": "not a regular file inside a managed root"})
                continue
            relative = resolved.relative_to(project_root)
        except (OSError, ValueError):
            manifest["skipped"].append({"path": str(source), "why": "cannot be expressed relative to the project root"})
            continue
        target = quarantine_dir / relative
        info = resolved.stat()
        entry = {"original": relative.as_posix(), "quarantine": relative.as_posix(), "size": info.st_size, "modified": _stamp(info.st_mtime), "sha256": _sha256(resolved),
                 "reason": item["reason"], "evidence": item["evidence"]}
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(resolved), str(target))
        entry["verified_after_move"] = _sha256(target) == entry["sha256"]
        manifest["entries"].append(entry)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["moved"] = len(manifest["entries"])
    manifest["bytes"] = sum(e["size"] for e in manifest["entries"])
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def restore(manifest_path: Path, roots: list[Path], apply: bool) -> list[dict]:
    """Move quarantined files back to their original paths. Refuses to overwrite, to restore outside a managed root, or to move a
    file whose checksum no longer matches the manifest. Without `apply` it only reports what it would do."""
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    project_root = Path(manifest["project_root"]).resolve()
    resolved_roots = [Path(root).resolve() for root in roots]
    outcome = []
    for entry in manifest["entries"]:
        row = {"original": entry["original"], "restored": False, "why": ""}
        original = (project_root / entry["original"]).resolve()
        held = (manifest_path.parent / entry["quarantine"]).resolve()
        if not _within(original, resolved_roots):
            row["why"] = "refused: original path is outside the managed directories"
        elif not held.is_file() or not held.is_relative_to(manifest_path.parent):
            row["why"] = "refused: quarantined file missing"
        elif _sha256(held) != entry["sha256"]:
            row["why"] = "refused: checksum differs from the manifest"
        elif original.exists():
            row["why"] = "refused: something already exists at the original path"
        elif not apply:
            row["why"] = "would restore"
        else:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(held), str(original))
            row["restored"], row["why"] = True, "restored"
        outcome.append(row)
    return outcome
