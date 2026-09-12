"""Agent runtime for the selected original AIWorkflow business schema.

Retired unified migrations are archived outside the active revision graph.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0019_original_agent_runtime'
down_revision = '0018_membership_agent'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'agent_turns',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('client_message_id', sa.String(length=100), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('input_revision', sa.Integer(), nullable=False),
        sa.Column('result_revision', sa.Integer(), nullable=True),
        sa.Column('model_calls', sa.Integer(), nullable=False),
        sa.Column('repair_calls', sa.Integer(), nullable=False),
        sa.Column('error_code', sa.String(length=40), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['agent_interactions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'client_message_id'),
    )
    op.create_index(op.f('ix_agent_turns_workspace_id'), 'agent_turns', ['workspace_id'], unique=False)
    op.create_table(
        'agent_workspace_messages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('turn_id', sa.Uuid(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['agent_interactions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'turn_id', 'role', 'ordinal'),
    )
    op.create_index(op.f('ix_agent_workspace_messages_workspace_id'), 'agent_workspace_messages', ['workspace_id'], unique=False)
    op.add_column('agent_interactions', sa.Column('revision', sa.Integer(), server_default='0', nullable=False))
    op.add_column('agent_interactions', sa.Column('active_turn_id', sa.Uuid(), nullable=True))
    op.add_column('agent_interactions', sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('agent_wait_goals', sa.Column('singleton_key', sa.Integer(), server_default='1', nullable=False))
    op.add_column('agent_wait_goals', sa.Column('revision', sa.Integer(), server_default='0', nullable=False))
    op.add_column('agent_wait_goals', sa.Column('holding_snapshot', sa.JSON(), server_default='{}', nullable=False))
    op.add_column('agent_wait_goals', sa.Column('conditions_schema_version', sa.Integer(), server_default='1', nullable=False))
    op.add_column('agent_wait_goals', sa.Column('last_checked_snapshot', sa.String(length=64), nullable=True))
    op.add_column('agent_wait_goals', sa.Column('result_id', sa.Uuid(), nullable=True))
    op.add_column('agent_wait_goals', sa.Column('result_version', sa.Integer(), server_default='0', nullable=False))
    op.add_column('agent_wait_goals', sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'agent_delivery_runs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('workspace_id', sa.Uuid(), sa.ForeignKey('agent_interactions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('client_message_id', sa.String(100), nullable=False),
        sa.Column('request', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('workspace_id', 'client_message_id'),
    )
    op.create_index('ix_agent_delivery_runs_workspace_id', 'agent_delivery_runs', ['workspace_id'])
    op.create_table(
        'agent_delivery_events',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('agent_delivery_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.UniqueConstraint('run_id', 'seq'),
    )
    op.create_index('ix_agent_delivery_events_run_id', 'agent_delivery_events', ['run_id'])
    op.create_table(
        'agent_run_checkpoints',
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
    op.create_table(
        'agent_artifacts',
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
    op.create_table(
        'agent_tool_calls',
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
    op.create_table(
        'agent_operation_receipts',
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
    op.add_column('agent_artifacts', sa.Column('created_by_turn_id', sa.Uuid(), nullable=True))
    op.create_index('uq_agent_presentation_call_scope', 'agent_artifacts', ['workspace_id', 'created_by_turn_id', 'created_by_call_id'], unique=True, postgresql_where=sa.text("kind = 'PRESENTATION' AND created_by_turn_id IS NOT NULL"), sqlite_where=sa.text("kind = 'PRESENTATION' AND created_by_turn_id IS NOT NULL"))
    op.add_column('agent_wait_goals', sa.Column('readiness', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('agent_wait_goals', sa.Column('seen_candidate_signatures', sa.JSON(), nullable=False, server_default='[]'))
    # These ingestion metadata columns already exist in the restored formal DB.
    inspector = sa.inspect(op.get_bind())
    if 'document_role' not in {c['name'] for c in inspector.get_columns('source_items')}:
        op.add_column('source_items', sa.Column('document_role', sa.String(30), nullable=True, server_default='OTHER'))
    if 'section_parser_version' not in {c['name'] for c in inspector.get_columns('document_versions')}:
        op.add_column('document_versions', sa.Column('section_parser_version', sa.String(100), nullable=True))


def downgrade():
    # Explicit rollback removes Agent runtime records; back up before invoking it.
    op.drop_table('agent_operation_receipts')
    op.drop_table('agent_tool_calls')
    op.drop_table('agent_artifacts')
    op.drop_table('agent_run_checkpoints')
    op.drop_table('agent_delivery_events')
    op.drop_table('agent_delivery_runs')
    op.drop_table('agent_workspace_messages')
    op.drop_table('agent_turns')
    op.drop_column('agent_wait_goals', 'seen_candidate_signatures')
    op.drop_column('agent_wait_goals', 'readiness')
    op.drop_column('agent_wait_goals', 'ended_at')
    op.drop_column('agent_wait_goals', 'result_version')
    op.drop_column('agent_wait_goals', 'result_id')
    op.drop_column('agent_wait_goals', 'last_checked_snapshot')
    op.drop_column('agent_wait_goals', 'conditions_schema_version')
    op.drop_column('agent_wait_goals', 'holding_snapshot')
    op.drop_column('agent_wait_goals', 'revision')
    op.drop_column('agent_wait_goals', 'singleton_key')
    op.drop_column('agent_interactions', 'lease_expires_at')
    op.drop_column('agent_interactions', 'active_turn_id')
    op.drop_column('agent_interactions', 'revision')
    # Keep the two ingestion metadata columns: they may predate this migration.
