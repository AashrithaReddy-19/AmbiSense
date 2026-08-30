"""Priority 2 cleanup audit ledger."""
from alembic import op
import sqlalchemy as sa

revision="20260823_priority2_complete"; down_revision="20260823_priority2"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("cleanup_audits",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("run_id",sa.String(36),nullable=False),sa.Column("session_id",sa.Integer()),sa.Column("action",sa.String(20),nullable=False),sa.Column("result",sa.String(20),nullable=False),sa.Column("details",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(),nullable=False)); op.create_index("ix_cleanup_audits_run_id","cleanup_audits",["run_id"]); op.create_index("ix_cleanup_audits_session_id","cleanup_audits",["session_id"])

def downgrade():
    op.drop_index("ix_cleanup_audits_session_id",table_name="cleanup_audits"); op.drop_index("ix_cleanup_audits_run_id",table_name="cleanup_audits"); op.drop_table("cleanup_audits")
