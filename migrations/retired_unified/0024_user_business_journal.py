"""Retain post-cutover user operations independently of expiring workspaces."""
from alembic import op
import sqlalchemy as sa

revision='0024_user_business_journal'
down_revision='0023_wait_seen_candidates'
branch_labels=depends_on=None


def upgrade():
    op.create_table('user_business_operations',
        sa.Column('sequence',sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column('operation_id',sa.Uuid(),nullable=False,unique=True),
        sa.Column('entity_kind',sa.String(20),nullable=False),
        sa.Column('entity_id',sa.Uuid(),nullable=False),
        sa.Column('before_state',sa.JSON()),sa.Column('after_state',sa.JSON()),
        sa.Column('payload_hash',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("entity_kind IN ('HOLDING','WAIT_GOAL')",name='ck_user_operation_kind'))


def downgrade():
    table=sa.table('user_business_operations',sa.column('sequence',sa.Integer()))
    if op.get_bind().scalar(sa.select(sa.func.count()).select_from(table)):
        raise RuntimeError('Retain the user-operation journal during rollback; replay and verify before retiring it')
    op.drop_table('user_business_operations')
