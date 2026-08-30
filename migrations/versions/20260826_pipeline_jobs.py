"""Persistent video jobs, source classification, and idempotent reports."""
from alembic import op
import sqlalchemy as sa

revision = "20260826_pipeline_jobs"
down_revision = "20260823_priority4_auth"
branch_labels = None
depends_on = None

def upgrade():
    inspector=sa.inspect(op.get_bind())
    if inspector.has_table("sessions"):
        with op.batch_alter_table("sessions") as batch:
            batch.add_column(sa.Column("source_filename", sa.String(255)))
            batch.add_column(sa.Column("job_id", sa.String(40)))
            batch.add_column(sa.Column("data_source", sa.String(16), server_default="REAL", nullable=False))
            batch.create_unique_constraint("uq_sessions_job_id", ["job_id"])
            batch.create_index("ix_sessions_data_source", ["data_source"])
        op.execute("UPDATE sessions SET is_test=1, data_source='TEST' WHERE lower(name) LIKE 'priority %' OR lower(name) LIKE 'p4 %' OR lower(name) LIKE 'api test%' OR lower(name) LIKE 'acceptance%' OR lower(name) LIKE 'websocket schema test%'")
    if inspector.has_table("reports"):
        with op.batch_alter_table("reports") as batch:
            batch.create_unique_constraint("uq_report_session_format", ["session_id", "format"])

def downgrade():
    inspector=sa.inspect(op.get_bind())
    if inspector.has_table("reports"):
        with op.batch_alter_table("reports") as batch: batch.drop_constraint("uq_report_session_format", type_="unique")
    if inspector.has_table("sessions"):
        with op.batch_alter_table("sessions") as batch:
            batch.drop_index("ix_sessions_data_source");batch.drop_constraint("uq_sessions_job_id", type_="unique");batch.drop_column("data_source");batch.drop_column("job_id");batch.drop_column("source_filename")
