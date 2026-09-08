"""Temporary, resumable workspace delivery events."""
from alembic import op
import sqlalchemy as sa
revision='0025_agent_delivery_events'
down_revision='0024_user_business_journal'
branch_labels=depends_on=None


def upgrade():
    op.create_table('agent_delivery_runs',sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('workspace_id',sa.Uuid(),sa.ForeignKey('agent_interactions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('client_message_id',sa.String(100),nullable=False),sa.Column('request',sa.JSON(),nullable=False),
        sa.Column('status',sa.String(30),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('workspace_id','client_message_id'))
    op.create_index('ix_agent_delivery_runs_workspace_id','agent_delivery_runs',['workspace_id'])
    op.create_table('agent_delivery_events',sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('run_id',sa.Uuid(),sa.ForeignKey('agent_delivery_runs.id',ondelete='CASCADE'),nullable=False),
        sa.Column('seq',sa.Integer(),nullable=False),sa.Column('kind',sa.String(30),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),sa.UniqueConstraint('run_id','seq'))
    op.create_index('ix_agent_delivery_events_run_id','agent_delivery_events',['run_id'])


def downgrade():
    op.drop_table('agent_delivery_events');op.drop_table('agent_delivery_runs')
