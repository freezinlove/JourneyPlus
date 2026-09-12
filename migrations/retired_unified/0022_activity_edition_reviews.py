"""Separate business edition decisions from migration audit records."""
import json
from datetime import datetime
from uuid import UUID
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision='0022_activity_edition_reviews'
down_revision='0021_explicit_free_currency'
branch_labels=depends_on=None


def upgrade():
    table=op.create_table('activity_edition_reviews',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('source_table',sa.String(40),nullable=False),
        sa.Column('source_id',sa.String(100),nullable=False),
        sa.Column('activity_id',sa.Uuid(),sa.ForeignKey('activities.id'),nullable=False),
        sa.Column('base_version_id',sa.Uuid()),
        sa.Column('decision',sa.String(20),nullable=False),
        sa.Column('target_activity_id',sa.Uuid(),sa.ForeignKey('activities.id')),
        sa.Column('reason',sa.Text(),nullable=False),
        sa.Column('request_json',sa.JSON().with_variant(postgresql.JSONB(),'postgresql'),nullable=False),
        sa.ForeignKeyConstraint(['base_version_id','activity_id'],['activity_knowledge_versions.id','activity_knowledge_versions.activity_id']),
        sa.CheckConstraint("decision IN ('SAME','NEW','UNRESOLVED')",name='ck_edition_review_decision'),
        sa.CheckConstraint("(decision='UNRESOLVED' AND target_activity_id IS NULL) OR (decision IN ('SAME','NEW') AND target_activity_id IS NOT NULL)",name='ck_edition_review_target'))
    op.create_index('ix_edition_review_source','activity_edition_reviews',['source_table','source_id','created_at'])
    # Preserve any reviews produced by the earlier development implementation.
    # Audit history remains; subsequent business reads use only the new table.
    bind=op.get_bind()
    for row in bind.execute(sa.text("SELECT * FROM knowledge_migration_links WHERE migration_version='activity-edition-v1'")).mappings():
        request=json.loads(row['reason'])
        identifier=UUID(row['legacy_path'].removeprefix('edition-review:'))
        times={key:datetime.fromisoformat(row[key]) if isinstance(row[key],str) else row[key] for key in ('created_at','updated_at')}
        bind.execute(table.insert().values(id=identifier,**times,
            source_table=row['legacy_table'],source_id=row['legacy_id'],activity_id=UUID(request['current_id']),
            base_version_id=UUID(request['expected_version']) if request['expected_version'] else None,
            decision=request['decision'],target_activity_id=UUID(str(row['target_id'])) if row['target_id'] else None,
            reason=request['reason'],request_json=request))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM activity_edition_reviews')):
        raise RuntimeError('Retain edition reviews during rollback; do not discard business decisions')
    op.drop_index('ix_edition_review_source',table_name='activity_edition_reviews')
    op.drop_table('activity_edition_reviews')
