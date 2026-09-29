"""scripts/init_database.py: safe, idempotent initialisation of fresh, current and legacy databases."""
import hashlib
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "init_database.py"


def _run(url, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), "--database-url", url, *extra], capture_output=True, text=True, cwd=ROOT)


def _tables(path):
    with sqlite3.connect(path) as connection:
        return {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}


def _revision(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("select version_num from alembic_version").fetchall()


def test_fresh_database_gets_schema_and_is_stamped_at_head(tmp_path):
    database = tmp_path / "fresh.db"
    result = _run(f"sqlite:///{database.as_posix()}")
    assert result.returncode == 0, result.stderr
    assert {"sessions", "analytics_snapshots", "reports", "users", "notifications", "alembic_version"} <= _tables(database)
    head = subprocess.run([sys.executable, "-m", "alembic", "heads"], capture_output=True, text=True, cwd=ROOT).stdout.split()[0]
    assert _revision(database) == [(head,)]


def test_running_it_twice_is_a_noop(tmp_path):
    database = tmp_path / "twice.db"
    url = f"sqlite:///{database.as_posix()}"
    assert _run(url).returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute("insert into classrooms (name, total_students, total_seats, active) values ('Kept room', 5, 5, 1)")
    second = _run(url)
    assert second.returncode == 0 and "already at head" in second.stdout
    with sqlite3.connect(database) as connection:
        assert connection.execute("select count(*) from classrooms where name='Kept room'").fetchone()[0] == 1


def test_dry_run_reports_the_action_and_changes_nothing(tmp_path):
    database = tmp_path / "dry.db"
    result = _run(f"sqlite:///{database.as_posix()}", "--dry-run")
    assert result.returncode == 0 and "create the schema from the models" in result.stdout and "Dry run" in result.stdout
    assert not database.exists() or _tables(database) == set()


def test_legacy_database_without_history_is_refused_untouched(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute("create table sessions (id integer primary key, name text)")
        connection.execute("insert into sessions values (1, 'legacy')")
    before = _tables(database)
    result = _run(f"sqlite:///{database.as_posix()}")
    assert result.returncode == 2
    assert "no Alembic history" in result.stdout and "Nothing was changed" in result.stdout
    assert _tables(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("select name from sessions").fetchall() == [("legacy",)]


REPAIR = ROOT / "scripts" / "repair_orphan_notifications.py"


def _repair(url, *extra):
    return subprocess.run([sys.executable, str(REPAIR), "--database-url", url, *extra], capture_output=True, text=True, cwd=ROOT)


def _seed_orphans(database):
    """Fresh schema, one real session, one notification that references it and one that references a missing session."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session as OrmSession

    from backend.app import models

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with OrmSession(engine) as db:
        session = models.Session(name="kept session", status="COMPLETED")
        db.add(session)
        db.flush()
        db.add(models.Notification(category="POOR_CAMERA", title="valid", message="m", dedupe_key="k-valid", session_id=session.id))
        db.commit()
        kept_id = session.id
    with engine.begin() as connection:  # bypass ORM: recreate what older deletion code left behind (no FK enforcement in SQLite by default)
        connection.execute(text("INSERT INTO notifications (category, title, message, evidence, dedupe_key, session_id, created_at) VALUES ('POOR_CAMERA', 'dangling', 'keep this text', '{}', 'k-dangling', 999, '2026-01-01 00:00:00')"))
    engine.dispose()
    return kept_id


def _rows(database):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute("select title, session_id, message from notifications order by title").fetchall()


def _fk_violations(database):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute("pragma foreign_key_check").fetchall()


def test_repair_reports_first_and_changes_nothing(tmp_path):
    database = tmp_path / "orphans.db"
    url = f"sqlite:///{database.as_posix()}"
    assert _run(url).returncode == 0
    kept_id = _seed_orphans(database)
    before, digest = _rows(database), hashlib.sha256(database.read_bytes()).hexdigest()
    assert len(_fk_violations(database)) == 1
    report = _repair(url)
    assert report.returncode == 0
    assert "1 notification(s) reference a session that no longer exists" in report.stdout
    assert "notification " in report.stdout and "missing session 999" in report.stdout
    assert "--apply" in report.stdout and "Nothing was changed" in report.stdout
    assert _rows(database) == before
    assert hashlib.sha256(database.read_bytes()).hexdigest() == digest  # byte-for-byte identical after a report-only run
    assert kept_id in [row[1] for row in before]


def test_apply_clears_only_dangling_references_keeps_rows_audits_and_is_idempotent(tmp_path):
    database = tmp_path / "orphans_apply.db"
    url = f"sqlite:///{database.as_posix()}"
    assert _run(url).returncode == 0
    kept_id = _seed_orphans(database)
    applied = _repair(url, "--apply")
    assert applied.returncode == 0 and "Cleared 1 dangling reference(s); no rows were deleted" in applied.stdout
    assert _rows(database) == [("dangling", None, "keep this text"), ("valid", kept_id, "m")]  # row and text kept, only the dead link cleared; valid link untouched
    assert _fk_violations(database) == []
    with closing(sqlite3.connect(database)) as connection:
        entries = connection.execute("select action, details from audit_entries where action='ORPHAN_NOTIFICATIONS_REPAIRED'").fetchall()
    assert len(entries) == 1 and '"cleared_references": 1' in entries[0][1]
    again = _repair(url, "--apply")
    assert again.returncode == 0 and "0 notification(s) reference a session that no longer exists" in again.stdout
    assert _rows(database) == [("dangling", None, "keep this text"), ("valid", kept_id, "m")]
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("select count(*) from audit_entries where action='ORPHAN_NOTIFICATIONS_REPAIRED'").fetchone()[0] == 1  # no second audit entry for a no-op


def test_repair_is_clean_on_a_database_without_orphans(tmp_path):
    database = tmp_path / "clean.db"
    url = f"sqlite:///{database.as_posix()}"
    assert _run(url).returncode == 0
    result = _repair(url, "--apply")
    assert result.returncode == 0 and "0 notification(s)" in result.stdout
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("select count(*) from audit_entries").fetchone()[0] == 0


def test_repair_rejects_non_sqlite_databases_safely():
    result = _repair("postgresql+psycopg://user:secret@localhost:5432/ambisense", "--apply")
    assert result.returncode == 2 and "only supports SQLite" in result.stdout
    assert "secret" not in result.stdout + result.stderr  # the URL (and its password) is never echoed


def test_repair_reports_a_missing_database_without_creating_one(tmp_path):
    database = tmp_path / "does_not_exist.db"
    result = _repair(f"sqlite:///{database.as_posix()}", "--apply")
    assert result.returncode == 2 and "Database file not found" in result.stdout and "Nothing was changed" in result.stdout
    assert not database.exists()


def test_repair_reports_an_unreadable_database_clearly(tmp_path):
    database = tmp_path / "corrupt.db"
    database.write_bytes(b"this is not a sqlite database at all" * 20)
    before = database.read_bytes()
    result = _repair(f"sqlite:///{database.as_posix()}")
    assert result.returncode == 2 and "Could not read the notifications table" in result.stdout and "Nothing was changed" in result.stdout
    assert database.read_bytes() == before


def test_repair_reports_a_database_without_the_notifications_table(tmp_path):
    database = tmp_path / "other.db"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("create table unrelated (id integer)")
    result = _repair(f"sqlite:///{database.as_posix()}", "--apply")
    assert result.returncode == 2 and "Could not read the notifications table" in result.stdout
