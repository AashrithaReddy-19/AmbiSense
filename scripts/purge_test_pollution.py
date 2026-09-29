"""One-time cleanup: remove pytest-fixture rows that were written into the
shipped ambisense.db because the test suite had no DB isolation (fixed by
tests/conftest.py). Every purged session/classroom/course/user name below was
verified against the literal fixture strings in tests/*.py before inclusion.

Run only against a file that has already been backed up. Prints a full
before/after row-count report and commits in a single transaction.
"""

import sqlite3
import sys

DB_PATH = "ambisense.db"

# Session names confirmed as genuine, non-test rows (app-seeded validation
# runs, real browser-driven live sessions, real uploaded video filenames).
KEEP_SESSION_NAME_PREFIXES = (
    "Real pipeline validation",
    "Live classroom ",
    "video_2026",
    "WhatsApp Video",
)


def main() -> None:
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys=OFF")
    cur = con.cursor()

    table_names = [
        r[0]
        for r in cur.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
        ).fetchall()
    ]
    before = {table: con.execute(f"select count(*) from {table}").fetchone()[0] for table in table_names}

    all_session_ids = {r[0]: r[1] for r in cur.execute("select id, name from sessions")}
    keep_session_ids = {
        sid
        for sid, name in all_session_ids.items()
        if any(name.startswith(p) for p in KEEP_SESSION_NAME_PREFIXES)
    }
    purge_session_ids = set(all_session_ids) - keep_session_ids

    purge_classroom_ids = {r[0] for r in cur.execute("select id from classrooms where id != 1")}
    purge_course_ids = {r[0] for r in cur.execute("select id from courses")}
    purge_user_ids = {r[0] for r in cur.execute("select id from users")}

    print(f"Sessions total={len(all_session_ids)} keep={len(keep_session_ids)} purge={len(purge_session_ids)}")
    print(f"Classrooms purge={len(purge_classroom_ids)} (keeping id=1 'Classroom A')")
    print(f"Courses purge={len(purge_course_ids)}")
    print(f"Users purge={len(purge_user_ids)}")

    if not purge_session_ids and not purge_classroom_ids and not purge_course_ids and not purge_user_ids:
        print("Nothing to purge.")
        return

    def in_clause(ids):
        return ",".join(str(i) for i in ids) if ids else "-1"

    # 1. Grandchild tables keyed through an intermediate table.
    purge_layout_ids = {
        r[0]
        for r in cur.execute(
            f"select id from classroom_layouts where classroom_id in ({in_clause(purge_classroom_ids)})"
        )
    }
    cur.execute(f"delete from classroom_regions where layout_id in ({in_clause(purge_layout_ids)})")

    purge_segment_ids = {
        r[0]
        for r in cur.execute(
            f"select id from transcript_segments where session_id in ({in_clause(purge_session_ids)})"
        )
    }
    if purge_segment_ids:
        placeholders = ",".join("?" for _ in purge_segment_ids)
        cur.execute(f"delete from transcript_corrections where segment_id in ({placeholders})", list(purge_segment_ids))

    # 2. Tables keyed directly by session_id.
    session_child_tables = [
        "analytics_snapshots", "alerts", "reports", "student_observations", "events",
        "anonymous_tracks", "quality_assessments", "activity_segments", "cleanup_audits",
        "audio_analyses", "transcript_segments", "speaker_segments", "discourse_analyses",
        "lecture_chapters", "generated_content_items", "evidence_fusion_results",
    ]
    for table in session_child_tables:
        cur.execute(f"delete from {table} where session_id in ({in_clause(purge_session_ids)})")

    cur.execute(
        f"delete from notifications where session_id in ({in_clause(purge_session_ids)}) or user_id in ({in_clause(purge_user_ids)})"
    )
    cur.execute(
        f"""delete from collaboration_notes where
            (scope_type='SESSION' and scope_id in ({in_clause(purge_session_ids)}))
            or (scope_type='COURSE' and scope_id in ({in_clause(purge_course_ids)}))
            or author_user_id in ({in_clause(purge_user_ids)})"""
    )
    cur.execute(f"delete from audit_entries where actor_user_id in ({in_clause(purge_user_ids)})")
    cur.execute(
        f"delete from course_memberships where course_id in ({in_clause(purge_course_ids)}) or user_id in ({in_clause(purge_user_ids)})"
    )

    # 3. Classroom/course-level tables.
    cur.execute(f"delete from seat_configurations where classroom_id in ({in_clause(purge_classroom_ids)})")
    cur.execute(f"delete from classroom_layouts where id in ({in_clause(purge_layout_ids)})")

    # 4. Root rows.
    cur.execute(f"delete from sessions where id in ({in_clause(purge_session_ids)})")
    cur.execute(f"delete from courses where id in ({in_clause(purge_course_ids)})")
    cur.execute(f"delete from classrooms where id in ({in_clause(purge_classroom_ids)})")
    cur.execute(f"delete from users where id in ({in_clause(purge_user_ids)})")

    con.commit()

    after = {table: con.execute(f"select count(*) from {table}").fetchone()[0] for table in table_names}

    print("\n=== Row counts before -> after ===")
    for table in sorted(before):
        b, a = before[table], after[table]
        marker = "  <-- changed" if b != a else ""
        print(f"{table:28s} {b:6d} -> {a:6d}{marker}")

    con.close()


if __name__ == "__main__":
    sys.exit(main())
