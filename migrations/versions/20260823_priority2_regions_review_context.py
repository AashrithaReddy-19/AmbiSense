"""Priority 2 layouts, event review, activity context and session management."""
from alembic import op
import sqlalchemy as sa

revision="20260823_priority2"; down_revision="20260822_priority1"; branch_labels=None; depends_on=None

def upgrade():
    op.add_column("classrooms",sa.Column("building",sa.String(120))); op.add_column("classrooms",sa.Column("room",sa.String(80))); op.add_column("classrooms",sa.Column("reference_image_path",sa.Text()))
    op.add_column("sessions",sa.Column("activity_context",sa.String(40),server_default="LECTURE",nullable=False)); op.add_column("sessions",sa.Column("archived",sa.Boolean(),server_default=sa.false(),nullable=False)); op.add_column("sessions",sa.Column("is_test",sa.Boolean(),server_default=sa.false(),nullable=False))
    op.add_column("student_observations",sa.Column("region_id",sa.String(80)))
    op.create_index("ix_student_observations_region_id","student_observations",["region_id"])
    op.add_column("events",sa.Column("end_timestamp",sa.Float())); op.add_column("events",sa.Column("confidence",sa.Float())); op.add_column("events",sa.Column("region_id",sa.String(80))); op.add_column("events",sa.Column("affected_tracks",sa.Integer(),server_default="0",nullable=False)); op.add_column("events",sa.Column("evidence_coverage",sa.Float())); op.add_column("events",sa.Column("model_version",sa.String(80))); op.add_column("events",sa.Column("review_state",sa.String(20),server_default="UNREVIEWED",nullable=False)); op.add_column("events",sa.Column("reviewer_note",sa.Text())); op.add_column("events",sa.Column("included_in_report",sa.Boolean(),server_default=sa.true(),nullable=False))
    op.create_table("classroom_layouts",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("classroom_id",sa.Integer(),sa.ForeignKey("classrooms.id"),nullable=False),sa.Column("name",sa.String(120),nullable=False),sa.Column("version",sa.Integer(),nullable=False),sa.Column("active",sa.Boolean(),nullable=False),sa.Column("reference_image_path",sa.Text()),sa.Column("created_at",sa.DateTime(),nullable=False),sa.UniqueConstraint("classroom_id","version",name="uq_classroom_layout_version")); op.create_index("ix_classroom_layouts_classroom_id","classroom_layouts",["classroom_id"])
    op.create_table("classroom_regions",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("layout_id",sa.Integer(),sa.ForeignKey("classroom_layouts.id"),nullable=False),sa.Column("region_key",sa.String(80),nullable=False),sa.Column("name",sa.String(120),nullable=False),sa.Column("region_type",sa.String(32),nullable=False),sa.Column("polygon",sa.JSON(),nullable=False),sa.Column("active",sa.Boolean(),nullable=False)); op.create_index("ix_classroom_regions_layout_id","classroom_regions",["layout_id"])
    op.create_table("activity_segments",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("session_id",sa.Integer(),sa.ForeignKey("sessions.id"),nullable=False),sa.Column("activity_type",sa.String(40),nullable=False),sa.Column("custom_label",sa.String(120)),sa.Column("start_seconds",sa.Float(),nullable=False),sa.Column("end_seconds",sa.Float()),sa.Column("confirmed",sa.Boolean(),nullable=False),sa.UniqueConstraint("session_id","start_seconds",name="uq_activity_session_start")); op.create_index("ix_activity_segments_session_id","activity_segments",["session_id"])

def downgrade():
    op.drop_table("activity_segments"); op.drop_table("classroom_regions"); op.drop_table("classroom_layouts"); op.drop_index("ix_student_observations_region_id",table_name="student_observations")
    with op.batch_alter_table("student_observations") as b: b.drop_column("region_id")
    with op.batch_alter_table("events") as b:
        for name in ("included_in_report","reviewer_note","review_state","model_version","evidence_coverage","affected_tracks","region_id","confidence","end_timestamp"): b.drop_column(name)
    with op.batch_alter_table("sessions") as b:
        for name in ("is_test","archived","activity_context"): b.drop_column(name)
    with op.batch_alter_table("classrooms") as b:
        for name in ("reference_image_path","room","building"): b.drop_column(name)
