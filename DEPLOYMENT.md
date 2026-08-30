# Deployment

For local Windows development, copy `.env.example` to `.env`, install backend and frontend dependencies, and run `./start_all.ps1`. For containers, run `docker compose up --build`. The Compose file currently provides FastAPI, the built frontend, PostgreSQL, and Redis.

Local processing uses FastAPI background tasks. Celery/Redis worker execution, authentication/RBAC, production secrets, HTTPS, rate limiting, object storage, and retention workers remain pending and are required before production use.

Apply migrations with `python -m alembic upgrade head` after installing `backend/requirements.txt`. Back up an existing database first. Repositories created before Alembic already contain the legacy tables but no `alembic_version`; inspect that schema and stamp its matching Priority revision before upgrading. Do not run the additive chain from revision zero against an already-created legacy database, because its columns already exist.
