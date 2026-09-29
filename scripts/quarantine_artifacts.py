"""Move PROVEN automated-test artifacts out of videos\\ and reports\\ into a timestamped quarantine folder. Nothing is deleted.

    python scripts/quarantine_artifacts.py                                   # dry run: what would move, and the proof for each file
    python scripts/quarantine_artifacts.py --apply                           # move them to backups\\quarantine_artifacts_<timestamp>\\
    python scripts/quarantine_artifacts.py --restore <manifest.json>         # dry run of the restore
    python scripts/quarantine_artifacts.py --restore <manifest.json> --apply # put every file back

A file is moved only if the artifact audit calls it UNREFERENCED (no database row points at it) and it is PROVEN to be an
automated-test artifact: either it is named for a session that a recorded cleanup run deleted and whose recorded name is a test
fixture name, or it is an uploaded video that decodes as a tiny synthetic clip. Referenced files, UNKNOWN files, symbolic links,
directories and anything outside the managed folders are never touched. The manifest records original path, size, modified time,
SHA-256 and the proof, and the restore refuses to overwrite anything or to accept a file whose checksum changed.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _size(value: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value} B"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", help="Override DATABASE_URL (SQLite file URLs only).")
    parser.add_argument("--upload-dir", help="Override UPLOAD_DIR.")
    parser.add_argument("--report-dir", help="Override REPORT_DIR.")
    parser.add_argument("--project-root", help="Folder that paths in the manifest are relative to (default: this repository).")
    parser.add_argument("--quarantine-dir", help="Where to move files (default: backups/quarantine_artifacts_<timestamp>).")
    parser.add_argument("--restore", metavar="MANIFEST", help="Restore the files listed in a manifest.json.")
    parser.add_argument("--apply", action="store_true", help="Actually move (or restore) the files. Without it nothing changes.")
    parser.add_argument("--json", action="store_true", help="Print the dry-run proposal as JSON.")
    args = parser.parse_args(argv)
    for name, value in (("DATABASE_URL", args.database_url), ("UPLOAD_DIR", args.upload_dir), ("REPORT_DIR", args.report_dir)):
        if value:
            os.environ[name] = value

    from backend.app.config import get_settings
    from backend.app.services import artifact_audit

    settings = get_settings()
    project_root = Path(args.project_root).resolve() if args.project_root else ROOT
    roots = [Path(settings.upload_dir), Path(settings.report_dir), Path(settings.classroom_reference_dir)]

    if args.restore:
        manifest = Path(args.restore)
        if not manifest.is_file():
            print(f"Manifest not found: {manifest.name}. Nothing was changed.")
            return 2
        rows = artifact_audit.restore(manifest, roots, args.apply)
        for row in rows:
            print(f"{'RESTORED' if row['restored'] else row['why'].upper():<60} {row['original']}")
        refused = [r for r in rows if r["why"].startswith("refused")]
        print(f"\n{sum(r['restored'] for r in rows)} restored, {len(refused)} refused, {len(rows)} in the manifest." + ("" if args.apply else " Dry run: nothing was changed. Add --apply to restore."))
        return 1 if refused else 0

    url = settings.database_url
    if not url.startswith("sqlite:///"):
        print("This tool only supports SQLite. Nothing was changed.")
        return 2
    database = Path(url.removeprefix("sqlite:///"))
    if not database.is_file():
        print(f"Database file not found: {database.name}. Nothing was changed.")
        return 2
    try:
        result = artifact_audit.audit(database, roots, project_root)
        proven, left = artifact_audit.find_proven_test_artifacts(result, database)
    except Exception as error:
        print(f"Could not audit ({type(error).__name__}). Nothing was changed.")
        return 2
    summary = result.summary()
    untouched = {"referenced": summary["by_classification"]["REFERENCED_REAL"]["files"] + summary["by_classification"]["REFERENCED_TEST"]["files"],
                 "unknown": summary["by_classification"]["UNKNOWN"]["files"], "unreferenced_but_not_proven": len(left)}
    total = sum(item["record"].size for item in proven)

    if args.json and not args.apply:
        print(json.dumps({"would_move": [{"path": i["record"].path, "size": i["record"].size, "reason": i["reason"], "evidence": i["evidence"]} for i in proven],
                          "bytes": total, "untouched": untouched, "unproven_unreferenced": [r.path for r in left]}, indent=2))
        return 0

    by_reason: dict[str, list] = {}
    for item in proven:
        by_reason.setdefault(item["reason"], []).append(item)
    for reason, items in by_reason.items():
        print(f"\n{len(items)} file(s), {_size(sum(i['record'].size for i in items))}: {reason}")
        for item in items[:3]:
            print(f"   e.g. {Path(item['record'].path).name}  proof: {item['evidence']}")
    print(f"\nProposed move: {len(proven)} file(s), {_size(total)}.")
    print(f"Left untouched: {untouched['referenced']} referenced, {untouched['unknown']} unknown, {untouched['unreferenced_but_not_proven']} unreferenced but not proven to be test artifacts.")

    if not args.apply:
        print("Dry run: nothing was changed. Add --apply to move the proposed files into quarantine (nothing is deleted).")
        return 0
    target = Path(args.quarantine_dir) if args.quarantine_dir else project_root / "backups" / time.strftime("quarantine_artifacts_%Y%m%d_%H%M%S")
    if artifact_audit._within(target.resolve(), [Path(r).resolve() for r in roots]):
        print("The quarantine folder must be outside the managed artifact folders. Nothing was changed.")
        return 2
    manifest = artifact_audit.quarantine(proven, target, project_root, roots, database.name)
    print(f"\nMoved {manifest['moved']} file(s), {_size(manifest['bytes'])}, into {target}")
    print(f"Manifest: {target / 'manifest.json'}   (skipped: {len(manifest['skipped'])}; every move re-verified by checksum: {all(e['verified_after_move'] for e in manifest['entries'])})")
    print(f"Restore with: python scripts\\quarantine_artifacts.py --restore \"{target / 'manifest.json'}\" --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
