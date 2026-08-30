"""Priority 4 signed-token credentials and revocation version."""
from alembic import op
import sqlalchemy as sa
revision="20260823_priority4_auth";down_revision="20260823_priority4";branch_labels=None;depends_on=None
def upgrade():op.add_column("users",sa.Column("password_hash",sa.Text()));op.add_column("users",sa.Column("token_version",sa.Integer(),server_default="0",nullable=False))
def downgrade():
 with op.batch_alter_table("users") as b:b.drop_column("token_version");b.drop_column("password_hash")
