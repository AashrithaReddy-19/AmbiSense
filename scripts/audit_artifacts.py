"""Audit files in the managed artifact directories against the database. Report-only by default.

    python scripts/audit_artifacts.py                          # table of every file and its classification
    python scripts/audit_artifacts.py --json                   # machine-readable
    python scripts/audit_artifacts.py --only UNREFERENCED      # filter (repeatable)
    python scripts/audit_artifacts.py --delete PATH [PATH ...]           # preview what deleting those files would do
    python scripts/audit_artifacts.py --delete PATH [PATH ...] --apply   # actually delete exactly those files

Classifications: REFERENCED_REAL, REFERENCED_TEST (a session row - or a file name generated for an existing session -
points at it), UNREFERENCED (nothing points at it and its name is one the application generates), UNKNOWN (anything else,
including symbolic links and files outside the managed roots).

The database is opened read-only. Deletion needs both --delete with explicit file paths AND --apply. Only regular files that
resolve inside the managed directories and are classified UNREFERENCED are eligible: no directories, no wildcards, no
symbolic links, nothing a database row references. Back up first; a deleted upload cannot be regenerated.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", help="Override DATABASE_URL (SQLite file URLs only).")
    parser.add_argument("--upload-dir", help="Override UPLOAD_DIR.")
    parser.add_argument("--report-dir", help="Override REPORT_DIR.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table.")
    parser.add_argument("--only", action="append", choices=("REFERENCED_REAL", "REFERENCED_TEST", "UNREFERENCED", "UNKNOWN"), help="Show only these classifications.")
    parser.add_argument("--delete", nargs="+", metavar="PATH", help="Explicit files to delete (preview unless --apply is also given).")
    parser.add_argument("--apply", action="store_true", help="With --delete: actually delete the eligible files.")
    args = parser.parse_args(argv)
    if args.apply and not args.delete:
        print("--apply needs --delete with explicit file paths. Nothing was changed.")
        return 2
    for name, value in (("DATABASE_URL", args.database_url), ("UPLOAD_DIR", args.upload_dir), ("REPORT_DIR", args.report_dir)):
        if value:
            os.environ[name] = value

    from backend.app.config import get_settings
    from backend.app.services import artifact_audit

    settings = get_settings()
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        print("This audit only supports SQLite. Nothing was changed.")
        return 2
    database = Path(url.removeprefix("sqlite:///"))
    if not database.is_file():
        print(f"Database file not found: {database.name}. Nothing was changed.")
        return 2
    roots = [Path(settings.upload_dir), Path(settings.report_dir), Path(settings.classroom_reference_dir)]
    try:
        result = artifact_audit.audit(database, roots, ROOT)
    except Exception as error:  # unreadable/corrupt database, permissions
        print(f"Could not audit ({type(error).__name__}). Nothing was changed.")
        return 2

    if args.delete:
        plan = artifact_audit.plan_deletion(args.delete, result, roots)
        outcome = artifact_audit.delete_selected(plan) if args.apply else plan
        for entry in outcome:
            verdict = ("DELETED" if entry.get("deleted") else "NOT DELETED") if args.apply else ("WOULD DELETE" if entry["allowed"] else "REFUSED")
            print(f"{verdict}: {entry['path'] or entry['requested']} - {entry['reason']}")
        if not args.apply:
            print("Preview only. Add --apply to delete the files marked WOULD DELETE. Nothing was changed.")
        return 0 if all(entry["allowed"] for entry in plan) else 1

    records = [record for record in result.records if not args.only or record.classification in args.only]
    if args.json:
        print(json.dumps({"roots": result.roots, "summary": result.summary(), "files": [record.as_dict() for record in records], "referenced_but_missing": result.missing_referenced}, indent=2))
        return 0
    for record in records:
        association = f"session {record.session_id}" if record.session_id is not None else "-"
        if record.report_id is not None:
            association += f" / report {record.report_id}"
        print(f"{record.classification:<16} {_format_size(record.size):>9}  {record.modified}  managed={'yes' if record.in_managed_dir else 'NO '}  {association:<24} {record.path}")
    summary = result.summary()
    print(f"\n{summary['files']} file(s) audited under: {', '.join(result.roots)}")
    for name, count in summary["by_classification"].items():
        print(f"  {name:<16} {count['files']:>5} file(s)  {_format_size(count['bytes'])}")
    print(f"  {summary['referenced_but_missing']} database reference(s) point at a file that is not on disk.")
    print("Report only. Nothing was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
