"""Add isolated model-led runtime storage without changing published knowledge."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0026_agent_harness"
down_revision = "0025_agent_delivery_events"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('agent_run_checkpoints',
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('agent_delivery_runs.id', ondelete='CASCADE'), nullable=False, primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('agent_interactions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('turn_id', sa.Uuid(), sa.ForeignKey('agent_turns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('phase', sa.String(30), nullable=False),
        sa.Column('model_attempt', sa.Integer(), nullable=False),
        sa.Column('pending_calls', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('remaining_budget', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('last_message_ordinal', sa.Integer(), nullable=False),
        sa.Column('cancel_requested', sa.Boolean(), nullable=False),
        sa.Column('lease_owner', sa.Uuid(), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revision', sa.Integer(), nullable=False),
    )
    op.create_index('ix_agent_run_checkpoints_workspace_id', 'agent_run_checkpoints', ['workspace_id'], unique=False)
    op.create_table('agent_artifacts',
        sa.Column('id', sa.Uuid(), nullable=False, primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('agent_interactions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('source_refs', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('created_by_call_id', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_agent_artifact_scope_kind_time', 'agent_artifacts', ['workspace_id', 'kind', 'created_at'], unique=False)
    op.create_table('agent_tool_calls',
        sa.Column('id', sa.Uuid(), nullable=False, primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('agent_interactions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('turn_id', sa.Uuid(), sa.ForeignKey('agent_turns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_call_id', sa.String(200), nullable=False),
        sa.Column('tool_name', sa.String(100), nullable=False),
        sa.Column('tool_version', sa.String(30), nullable=False),
        sa.Column('arguments', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('arguments_hash', sa.String(64), nullable=False),
        sa.Column('effect', sa.String(30), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('result_artifact_id', sa.Uuid(), sa.ForeignKey('agent_artifacts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('operation_ref', sa.String(100), nullable=True),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=True),
        sa.UniqueConstraint('turn_id', 'provider_call_id'),
    )
    op.create_index('ix_agent_tool_calls_workspace_id', 'agent_tool_calls', ['workspace_id'], unique=False)
    op.create_table('agent_operation_receipts',
        sa.Column('id', sa.Uuid(), nullable=False, primary_key=True),
        sa.Column('owner_key', sa.String(100), nullable=False),
        sa.Column('idempotency_key', sa.String(500), nullable=False),
        sa.Column('operation_kind', sa.String(40), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('entity_kind', sa.String(30), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('before', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=True),
        sa.Column('after', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=True),
        sa.Column('authorization_snapshot', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_key', 'idempotency_key'),
    )


def downgrade():
# Manual downgrade only; application rollback must retain durable receipts.
    op.drop_table('agent_tool_calls')
    op.drop_table('agent_artifacts')
    op.drop_table('agent_run_checkpoints')
    op.drop_table('agent_operation_receipts')
