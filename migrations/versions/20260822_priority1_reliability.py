"""Priority 1 reliability, occupancy, tracks and quality."""
from alembic import op
import sqlalchemy as sa

revision="20260822_priority1"; down_revision=None; branch_labels=None; depends_on=None

def upgrade():
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("retry_count",sa.Integer(),server_default="0",nullable=False)); batch.add_column(sa.Column("failure_code",sa.String(40))); batch.add_column(sa.Column("internal_error_reference",sa.String(40)))
    with op.batch_alter_table("analytics_snapshots") as batch:
        batch.add_column(sa.Column("current_occupancy_count",sa.Integer(),server_default="0",nullable=False)); batch.add_column(sa.Column("peak_occupancy_count",sa.Integer(),server_default="0",nullable=False)); batch.add_column(sa.Column("occupancy_rate",sa.Float())); batch.add_column(sa.Column("estimated_unique_tracks",sa.Integer(),server_default="0",nullable=False)); batch.add_column(sa.Column("verified_attendance_rate",sa.Float()))
    op.create_table("anonymous_tracks",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("session_id",sa.Integer(),sa.ForeignKey("sessions.id"),nullable=False),sa.Column("track_uuid",sa.String(36),nullable=False),sa.Column("tracker_local_id",sa.Integer(),nullable=False),sa.Column("first_seen",sa.Float(),nullable=False),sa.Column("last_seen",sa.Float(),nullable=False),sa.Column("observation_count",sa.Integer(),nullable=False),sa.Column("visible_duration",sa.Float(),nullable=False),sa.Column("average_confidence",sa.Float(),nullable=False),sa.Column("last_bbox",sa.JSON(),nullable=False),sa.Column("region_id",sa.String(80)),sa.Column("active",sa.Boolean(),nullable=False),sa.Column("expiry_reason",sa.String(40)),sa.UniqueConstraint("session_id","track_uuid",name="uq_session_track_uuid")); op.create_index("ix_anonymous_tracks_session_id","anonymous_tracks",["session_id"])
    op.create_table("quality_assessments",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("session_id",sa.Integer(),sa.ForeignKey("sessions.id"),nullable=False),sa.Column("timestamp",sa.Float(),nullable=False),sa.Column("overall_quality",sa.Float()),sa.Column("status",sa.String(24),nullable=False),sa.Column("details",sa.JSON(),nullable=False),sa.UniqueConstraint("session_id","timestamp",name="uq_quality_session_time")); op.create_index("ix_quality_assessments_session_id","quality_assessments",["session_id"])

def downgrade():
    op.drop_table("quality_assessments"); op.drop_table("anonymous_tracks")
    with op.batch_alter_table("analytics_snapshots") as batch:
        for name in ("verified_attendance_rate","estimated_unique_tracks","occupancy_rate","peak_occupancy_count","current_occupancy_count"): batch.drop_column(name)
    with op.batch_alter_table("sessions") as batch:
        for name in ("internal_error_reference","failure_code","retry_count"): batch.drop_column(name)
