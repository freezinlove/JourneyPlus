"""Private holdings and one renewable workspace per account."""
from alembic import op
import sqlalchemy as sa
revision='0020_minimal_users'
down_revision='0019_original_agent_runtime'
branch_labels=None
depends_on=None
OWNER='00000000-0000-0000-0000-000000000001'

def upgrade():
    op.create_table('user_accounts',sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('username',sa.String(100),nullable=False,unique=True),sa.Column('password_hash',sa.String(300),nullable=False),
        sa.Column('current_workspace_id',sa.Uuid(),nullable=True),sa.Column('failed_logins',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('locked_until',sa.DateTime(timezone=True),nullable=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    # Disabled until owner initializes a password. Never a hard-coded login secret.
    op.execute(sa.text("INSERT INTO user_accounts (id,username,password_hash) VALUES (CAST(:id AS UUID),'owner','!uninitialized')").bindparams(id=OWNER))
    op.create_table('login_sessions',sa.Column('token_hash',sa.String(64),primary_key=True),
        sa.Column('user_id',sa.Uuid(),sa.ForeignKey('user_accounts.id',ondelete='CASCADE'),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_login_sessions_user_id','login_sessions',['user_id'])
    for table in ('status_holdings','agent_interactions'):
        op.add_column(table,sa.Column('user_id',sa.Uuid(),nullable=False,server_default=OWNER))
        op.create_index('ix_'+table+'_user_id',table,['user_id'])
        op.create_foreign_key('fk_'+table+'_user',table,'user_accounts',['user_id'],['id'])
    op.add_column('agent_interactions',sa.Column('last_message_at',sa.DateTime(timezone=True),nullable=True))
    for c in sa.inspect(op.get_bind()).get_unique_constraints('status_holdings'):
        if c['column_names']==['program_key']:op.drop_constraint(c['name'],'status_holdings',type_='unique')
    op.create_unique_constraint('uq_holding_user_program','status_holdings',['user_id','program_key'])
    op.execute(sa.text("UPDATE user_accounts SET current_workspace_id=(SELECT id FROM agent_interactions WHERE schema_version='harness-2' AND expires_at>CURRENT_TIMESTAMP ORDER BY updated_at DESC LIMIT 1) WHERE id=CAST(:id AS UUID)").bindparams(id=OWNER))
    # Old conversations are retained for migration review but inaccessible unless current.
    op.execute(sa.text("UPDATE agent_operation_receipts SET owner_key=:id WHERE owner_key='local-user'").bindparams(id=OWNER))

def downgrade():
    raise RuntimeError('Multi-user holdings cannot safely be merged into a global unique program. Restore a backup instead.')
