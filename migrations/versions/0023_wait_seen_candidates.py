"""Preserve material candidate identities across explicit waiting rounds."""
from alembic import op
import sqlalchemy as sa

revision='0023_wait_seen_candidates'
down_revision='0022_activity_edition_reviews'
branch_labels=depends_on=None


def upgrade():
    op.add_column('agent_wait_goals',sa.Column('seen_candidate_signatures',sa.JSON(),nullable=False,server_default='[]'))


def downgrade():
    table=sa.table('agent_wait_goals',sa.column('seen_candidate_signatures',sa.JSON()))
    if any(op.get_bind().scalars(sa.select(table.c.seen_candidate_signatures))):
        raise RuntimeError('Retain seen waiting results during rollback to avoid duplicate delivery')
    op.drop_column('agent_wait_goals','seen_candidate_signatures')
