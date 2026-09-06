"""Allow explicitly evidenced free fees without inventing a currency."""
from alembic import op
import sqlalchemy as sa
revision = '0021_explicit_free_currency'
down_revision = '0020_agent_workspaces'
branch_labels = depends_on = None
OLD = "(known_state = 'KNOWN' AND amount IS NOT NULL AND currency IS NOT NULL) OR (known_state IN ('UNKNOWN','CONFLICT','NOT_APPLICABLE') AND amount IS NULL)"
NEW = "(known_state = 'KNOWN' AND amount IS NOT NULL AND (amount = 0 OR currency IS NOT NULL)) OR (known_state IN ('UNKNOWN','CONFLICT','NOT_APPLICABLE') AND amount IS NULL)"
def upgrade():
    with op.batch_alter_table('option_prices') as batch:
        batch.drop_constraint('ck_price_known_state', type_='check')
        batch.create_check_constraint('ck_price_known_state', NEW)
def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM option_prices WHERE known_state='KNOWN' AND currency IS NULL")):
        raise RuntimeError('Published free fees have no source currency; retain the additive schema during rollback')
    with op.batch_alter_table('option_prices') as batch:
        batch.drop_constraint('ck_price_known_state', type_='check')
        batch.create_check_constraint('ck_price_known_state', OLD)
