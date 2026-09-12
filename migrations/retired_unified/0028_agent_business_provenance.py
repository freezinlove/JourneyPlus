"""Preserve user statements and explicit waiting readiness; no knowledge rewrites."""
from alembic import op
import sqlalchemy as sa

revision = '0028_agent_business_provenance'
down_revision = '0027_agent_artifact_turn_scope'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('status_holdings',sa.Column('source_record',sa.JSON(),nullable=False,server_default='{}'))
    op.add_column('agent_wait_goals',sa.Column('readiness',sa.JSON(),nullable=False,server_default='{}'))


def downgrade():
    op.drop_column('agent_wait_goals','readiness')
    op.drop_column('status_holdings','source_record')
