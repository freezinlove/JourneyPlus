"""Restore a schema-only archive into a disposable PostgreSQL database and test it.

No business data is copied. The disposable database is always removed.
"""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from journeyplus.config import Settings

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'doc/database-archives/2026-09-12-before-relaxation/schema.sql'


def main():
    url = sa.make_url(Settings.from_env().database_url)
    if url.host not in {'localhost', '127.0.0.1'} or url.database != 'journeyplus':
        raise RuntimeError('This verification requires the local journeyplus Compose database')
    name = 'journeyplus_constraint_test_' + uuid4().hex[:12]
    prefix = ['docker', 'compose', 'exec', '-T', 'postgres']

    def cli(*args, data=None):
        return subprocess.run(prefix + list(args), input=data, capture_output=True, check=True, cwd=ROOT)

    def apply(path):
        cli('psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', url.username, '-d', name, data=path.read_bytes())

    cli('createdb', '-U', url.username, name)
    engine = sa.create_engine(url.set(database=name))
    try:
        apply(ARCHIVE)
        # Check reversibility on the schema before introducing synthetic rows.
        apply(ROOT / 'migrations/manual/relax_workflow_constraints.sql')
        apply(ROOT / 'migrations/manual/restore_workflow_constraints.sql')
        apply(ROOT / 'migrations/manual/relax_workflow_constraints.sql')
        metadata = sa.MetaData()
        metadata.reflect(engine)
        assert len(metadata.tables) == 44
        with engine.begin() as c:
            def add(name, **values):
                table = metadata.tables[name]
                for col in table.c:
                    if col.name in values or col.nullable or col.server_default is not None:
                        continue
                    if isinstance(col.type, sa.Uuid): value = uuid4()
                    elif isinstance(col.type, sa.JSON): value = {}
                    elif isinstance(col.type, sa.Boolean): value = False
                    elif isinstance(col.type, sa.DateTime): value = datetime.now(timezone.utc)
                    elif isinstance(col.type, sa.Integer): value = 1
                    elif isinstance(col.type, sa.Numeric): value = 1
                    else: value = 'test_' + uuid4().hex[:10]
                    values[col.name] = value
                return c.execute(table.insert().values(**values).returning(table.c.id)).scalar_one()

            def rejected(statement):
                savepoint = c.begin_nested()
                try:
                    c.execute(statement)
                except IntegrityError:
                    savepoint.rollback()
                else:
                    savepoint.rollback()
                    raise AssertionError('Expected a retained integrity guard to reject the operation')

            source = add('sources')
            item = add('source_items', source_id=source)
            doc = add('document_versions', source_item_id=item)
            activity = add('activities', kind='STATUS_MATCH')
            binding = add('activity_source_bindings', activity_id=activity, source_item_id=item, status='BOUND')
            run = add('analysis_runs', activity_id=activity, source_binding_id=binding)
            version = add('activity_knowledge_versions', activity_id=activity, source_binding_id=binding,
                          analysis_run_id=run, status='DRAFT', version_no=1)
            second = add('activity_knowledge_versions', activity_id=activity, source_binding_id=binding,
                         analysis_run_id=run, status='DRAFT', version_no=2)
            assert version != second  # One analysis may produce more than one version.
            brief = add('activity_briefs', activity_id=activity, knowledge_version_id=version,
                        brief_kind='CURRENT', status='PENDING')
            supplements = metadata.tables['activity_supplements']
            supplement = add('activity_supplements', knowledge_version_id=second, document_version_id=doc)
            c.execute(supplements.update().where(supplements.c.id == supplement).values(highlights=['revised']))
            c.execute(supplements.delete().where(supplements.c.id == supplement))
            option = add('application_options', activity_id=activity)
            option_version = add('application_option_versions', activity_id=activity, knowledge_version_id=version,
                                 option_id=option, method='MATCH', availability='AVAILABLE')
            price = add('option_prices', option_version_id=option_version, knowledge_version_id=version,
                        target_scope='ALL_TARGETS', mapping_scope='ALL_MAPPINGS', amount=99,
                        currency='USD', known_state='KNOWN', fee_role='APPLICATION', combination='REQUIRED',
                        availability='UNAVAILABLE')
            prices = metadata.tables['option_prices']
            assert c.scalar(sa.select(prices.c.raw_text).where(prices.c.id == price)) == ''
            rejected(prices.update().where(prices.c.id == price).values(amount=-1))
            rejected(prices.update().where(prices.c.id == price).values(availability='INVALID'))
            versions = metadata.tables['activity_knowledge_versions']
            c.execute(versions.update().where(versions.c.id == version).values(status='PUBLISHED'))
            briefs = metadata.tables['activity_briefs']
            c.execute(briefs.update().where(briefs.c.id == brief).values(status='READY'))
            update_brief = add('activity_briefs', activity_id=activity, knowledge_version_id=version,
                               brief_kind='UPDATE', status='FAILED')
            c.execute(briefs.delete().where(briefs.c.id == update_brief))
            rejected(prices.update().where(prices.c.id == price).values(amount=100))
            rejected(versions.update().where(versions.c.id == version).values(facts={'changed': True}))
            docs = metadata.tables['document_versions']
            rejected(docs.update().where(docs.c.id == doc).values(raw_body='changed'))
            rejected(briefs.insert().values(activity_id=activity, knowledge_version_id=uuid4(),
                     brief_kind='CURRENT', status='READY', generator_version='test', content={}, fact_refs=[],
                     id=uuid4(), created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
            add('agent_wait_goals', conditions_schema_version=4)
        print('PASS: schema restore; upgrade/downgrade/upgrade; all six relaxed behaviors; '
              'retained foreign keys, published-fact protection, archive protection and price checks')
    finally:
        engine.dispose()
        cli('dropdb', '-U', url.username, name)


if __name__ == '__main__':
    main()
