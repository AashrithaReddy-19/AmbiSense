# Backup and restore

Back up **three things together**: the database, the artifact folders (`videos/`, `reports/`, `models/` if you added
model files) and your `.env`. Stop writers (or accept a point-in-time copy) so the database and files agree.
Nothing here is run automatically; restore in particular is always a deliberate, manual act.

## SQLite

**Backup** (safe while the app runs, consistent even with WAL/journal activity):

```powershell
python -c "import sqlite3,datetime;s=sqlite3.connect('file:ambisense.db?mode=ro',uri=True);d=sqlite3.connect('backups/ambisense_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.db');s.backup(d);print('ok')"
```

**Verify a backup** before you rely on it:

```powershell
python -c "import sqlite3;c=sqlite3.connect('file:backups/<file>.db?mode=ro',uri=True);print(c.execute('pragma integrity_check').fetchall(), len(c.execute('pragma foreign_key_check').fetchall()))"
```

**Restore** (manual): stop the application; **keep the current file** (`Rename-Item ambisense.db ambisense.before_restore.db`);
copy the chosen backup to `ambisense.db`; run `python scripts\init_database.py --dry-run` (expect *already at head* or a
pending upgrade); start the application. Never restore an older backup over a database you have not first preserved:
you would lose everything written since. If a backup pre-dates a data clean-up, restoring it brings back the removed rows.

## PostgreSQL

Write the dump **inside the container** and copy it out: PowerShell's `>` and `<` re-encode binary data and would corrupt a custom-format dump.

```powershell
docker compose exec postgres pg_dump -U ambisense -Fc -f /tmp/ambisense.dump ambisense
docker compose cp postgres:/tmp/ambisense.dump backups/ambisense_$(Get-Date -Format yyyyMMdd_HHmmss).dump
```

Restore into a **new, empty database** and switch `DATABASE_URL` after checking it, rather than over the live one:

```powershell
docker compose cp backups/<file>.dump postgres:/tmp/restore.dump
docker compose exec postgres createdb -U ambisense ambisense_restore
docker compose exec postgres pg_restore -U ambisense -d ambisense_restore --no-owner /tmp/restore.dump
```

## Artifacts

Copy `videos/` (original and annotated videos, reference images) and `reports/` (PDF/CSV/metrics, exports). In Docker they
are the named volumes `videos` and `reports`:

```powershell
docker run --rm -v ambisense_videos:/data -v ${PWD}/backups:/backup alpine tar czf /backup/videos.tgz -C /data .
```

The database stores file *paths*. If you restore a database without its artifacts, downloads return "not available"
(the *Artifacts* tab lists only files that exist) and reports can be regenerated for completed sessions.

## After deleting data

Permanent deletion (session or artifacts) is audited in the database, so a *database* backup taken earlier still contains the
deleted rows and a copy of any deleted files may exist in old artifact backups. When deletion is required for privacy
reasons, delete from the backups on the same schedule as the live data.
