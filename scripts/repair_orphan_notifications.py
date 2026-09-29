"""Find (and, only with --apply, repair) notifications that point at a session which no longer exists.

    python scripts/repair_orphan_notifications.py [--database-url URL]            # report only (default)
    python scripts/repair_orphan_notifications.py [--database-url URL] --apply    # clear the dangling reference

These rows appear when sessions were deleted by older code that did not remove their notifications; they show up as
`PRAGMA foreign_key_check` violations. Current deletion code removes notifications together with the session, so this
does not recur. The repair is deliberately minimal and non-destructive: it sets `notifications.session_id` to NULL
(the notification text stays; the dead deep link goes). Nothing is deleted. Back the database up before using --apply.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", help="Override DATABASE_URL (SQLite file URLs only).")
    parser.add_argument("--apply", action="store_true", help="Actually clear the dangling references.")
    args = parser.parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    from backend.app.config import get_settings

    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        print("This helper only supports SQLite; use SQL against PostgreSQL after a backup.")
        return 2
    path = Path(url.removeprefix("sqlite:///"))
    if not path.is_file():
        # sqlite3.connect would silently create an empty database here; refuse instead.
        print(f"Database file not found: {path.name}. Nothing was changed.")
        return 2
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode={'rw' if args.apply else 'ro'}", uri=True)
        connection.execute("SELECT 1 FROM notifications LIMIT 1")
    except sqlite3.DatabaseError as error:
        print(f"Could not read the notifications table ({type(error).__name__}). Nothing was changed.")
        return 2
    try:
        rows = connection.execute("SELECT id, session_id, category FROM notifications WHERE session_id IS NOT NULL AND session_id NOT IN (SELECT id FROM sessions)").fetchall()
        print(f"{len(rows)} notification(s) reference a session that no longer exists.")
        for row in rows[:20]:
            print(f"  notification {row[0]} -> missing session {row[1]} ({row[2]})")
        if not rows:
            return 0
        if not args.apply:
            print("Report only. Re-run with --apply (after a backup) to clear these references. Nothing was changed.")
            return 0
        with connection:
            connection.execute("UPDATE notifications SET session_id = NULL WHERE session_id IS NOT NULL AND session_id NOT IN (SELECT id FROM sessions)")
            connection.execute("INSERT INTO audit_entries (actor_user_id, action, resource_type, resource_id, details, created_at) VALUES (NULL, 'ORPHAN_NOTIFICATIONS_REPAIRED', 'NOTIFICATION', NULL, ?, datetime('now'))", (f'{{"cleared_references": {len(rows)}}}',))
        print(f"Cleared {len(rows)} dangling reference(s); no rows were deleted.")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
