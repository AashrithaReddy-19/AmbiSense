"""Idempotent database initialisation (SQLite or PostgreSQL).

    python scripts/init_database.py [--database-url URL] [--dry-run]

What it does, and why:

* A fresh, empty database: create the current schema from the models and stamp it at the
  Alembic head. (The migration chain starts from an already-existing base schema, so running
  ``alembic upgrade head`` on an empty database would fail.)
* A database that already has Alembic history: run ``alembic upgrade head`` (a no-op when current).
* A database that has tables but NO Alembic history (a legacy file): refuse and explain. Guessing a
  revision could skip or repeat migrations, so a human must back up and stamp it deliberately
  (see docs/DEPLOYMENT.md, "Alembic stamping for legacy databases").

``--dry-run`` reports what would happen and changes nothing. Exit codes: 0 ok, 2 needs manual action.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", help="Override DATABASE_URL for this run.")
    parser.add_argument("--dry-run", action="store_true", help="Report the action without changing the database.")
    args = parser.parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    from backend.app import models  # noqa: F401  (registers every table on Base.metadata)
    from backend.app.config import get_settings
    from backend.app.database import Base

    settings = get_settings()
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    tables = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    dialect = engine.dialect.name

    if not tables:
        action = "create the schema from the models and stamp it at head"
    elif current is None:
        print(f"[{dialect}] This database has tables but no Alembic history. Back it up, review docs/DEPLOYMENT.md, and stamp it manually. Nothing was changed.")
        return 2
    elif current == head:
        action = "nothing (already at head)"
    else:
        action = f"upgrade {current} -> {head}"
    print(f"[{dialect}] current={current or 'none'} head={head} action: {action}")
    if args.dry_run:
        print("Dry run: no changes made.")
        return 0

    if not tables:
        Base.metadata.create_all(engine)
        command.stamp(config, "head")
    elif current != head:
        command.upgrade(config, "head")
    print("Database is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
