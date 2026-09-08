"""Scope new presentation effects by workspace, turn and provider call id."""
from alembic import op
import sqlalchemy as sa

revision = '0027_agent_artifact_turn_scope'
down_revision = '0026_agent_harness'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('agent_artifacts', sa.Column('created_by_turn_id', sa.Uuid(), nullable=True))
    # Historical rows stay unbound: a provider id alone cannot prove its turn.
    op.create_index('uq_agent_presentation_call_scope', 'agent_artifacts',
        ['workspace_id', 'created_by_turn_id', 'created_by_call_id'], unique=True,
        postgresql_where=sa.text("kind = 'PRESENTATION' AND created_by_turn_id IS NOT NULL"),
        sqlite_where=sa.text("kind = 'PRESENTATION' AND created_by_turn_id IS NOT NULL"))


def downgrade():
    op.drop_index('uq_agent_presentation_call_scope', table_name='agent_artifacts')
    op.drop_column('agent_artifacts', 'created_by_turn_id')
