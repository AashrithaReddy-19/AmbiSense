"""Backfill indexes/constraints missing on databases that predate Alembic.

ambisense.db was never stamped with Alembic; its schema was kept current by
an ad hoc ALTER TABLE patcher (backend/app/database.py:ensure_session_columns)
that only adds columns, never indexes or constraints. As a result, columns
from every prior migration are present, but five index/constraint objects
those migrations also created are missing on tables that predate them
(classrooms, sessions, reports). This migration adds exactly those five,
guarded by inspector checks so it is a no-op on any database where Alembic
already applied them normally.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260920_backfill_legacy_constraints"
down_revision = "20260826_pipeline_jobs"
branch_labels = None
depends_on = None


def _existing_index_names(inspector, table):
    return {ix["name"] for ix in inspector.get_indexes(table)} | {
        uq["name"] for uq in inspector.get_unique_constraints(table) if uq.get("name")
    }


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("classrooms"):
        existing = _existing_index_names(inspector, "classrooms")
        if "ix_classrooms_owner_user_id" not in existing:
            op.create_index("ix_classrooms_owner_user_id", "classrooms", ["owner_user_id"])

    if inspector.has_table("sessions"):
        existing = _existing_index_names(inspector, "sessions")
        if "ix_sessions_course_id" not in existing:
            op.create_index("ix_sessions_course_id", "sessions", ["course_id"])
        if "ix_sessions_data_source" not in existing:
            op.create_index("ix_sessions_data_source", "sessions", ["data_source"])
        if "uq_sessions_job_id" not in existing:
            with op.batch_alter_table("sessions") as batch:
                batch.create_unique_constraint("uq_sessions_job_id", ["job_id"])

    if inspector.has_table("reports"):
        existing = _existing_index_names(inspector, "reports")
        if "uq_report_session_format" not in existing:
            with op.batch_alter_table("reports") as batch:
                batch.create_unique_constraint("uq_report_session_format", ["session_id", "format"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("reports"):
        existing = _existing_index_names(inspector, "reports")
        if "uq_report_session_format" in existing:
            with op.batch_alter_table("reports") as batch:
                batch.drop_constraint("uq_report_session_format", type_="unique")

    if inspector.has_table("sessions"):
        existing = _existing_index_names(inspector, "sessions")
        if "uq_sessions_job_id" in existing:
            with op.batch_alter_table("sessions") as batch:
                batch.drop_constraint("uq_sessions_job_id", type_="unique")
        if "ix_sessions_data_source" in existing:
            op.drop_index("ix_sessions_data_source", table_name="sessions")
        if "ix_sessions_course_id" in existing:
            op.drop_index("ix_sessions_course_id", table_name="sessions")

    if inspector.has_table("classrooms"):
        existing = _existing_index_names(inspector, "classrooms")
        if "ix_classrooms_owner_user_id" in existing:
            op.drop_index("ix_classrooms_owner_user_id", table_name="classrooms")
