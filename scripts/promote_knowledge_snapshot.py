"""Promote reviewed knowledge from a verified copy into an empty knowledge store.

Does not replace a database, copy user/workspace data, disable constraints, or run
models. Source documents and legacy identities must still exactly match the copy.
Use only after backing up the target and reviewing the copy's publication report.
"""
import argparse
import json
from pathlib import Path
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import make_url
from journeyplus.config import Settings
from journeyplus.models import Base
from journeyplus.knowledge import models  # register knowledge tables

TABLES = ['membership_programs','membership_tiers','membership_aliases','activities',
          'document_sections','evidence_references','activity_knowledge_versions',
          'application_options','application_option_versions','option_mappings',
          'option_prices','option_price_mappings','activity_documents','activity_briefs',
          'activity_observation_state','activity_edition_reviews','knowledge_migration_links']
SOURCES = ['sources','source_items','document_versions','status_events','fact_sets',
           'article_analyses','article_opportunities','statusmatch_watches','statusmatch_watch_pages']


def digest(conn, name, *, source_content=False):
    quoted=conn.dialect.identifier_preparer.quote(name)
    row="(to_jsonb(t)-'section_parser_version'-'updated_at')" if source_content and name=='document_versions' else 'to_jsonb(t)'
    return conn.execute(text(f"SELECT count(*),md5(coalesce(string_agg(md5({row}::text),'' ORDER BY md5({row}::text)),'')) FROM {quoted} t")).one()._asdict()


def promote(source_engine, target_engine):
    with source_engine.connect().execution_options(isolation_level='REPEATABLE READ') as source, target_engine.begin() as target:
        source.execute(text('SET TRANSACTION READ ONLY'))
        # All writes become visible atomically, with ordinary FK checks enabled.
        target.execute(text('SET LOCAL lock_timeout = \'5s\''))
        for name in [*SOURCES,*TABLES,'status_holdings']:
            target.execute(text('LOCK TABLE '+target.dialect.identifier_preparer.quote(name)+' IN SHARE ROW EXCLUSIVE MODE'))
        for name in SOURCES:
            if digest(source,name,source_content=True)!=digest(target,name,source_content=True):
                raise ValueError(f'Source changed since review: {name}')
        for name in TABLES:
            if target.scalar(select(text('count(*)')).select_from(Base.metadata.tables[name])):
                raise ValueError(f'Target knowledge must be empty: {name}')
        preserved=digest(target,'status_holdings')
        deferred=[];versions=[];counts={}
        for name in TABLES:
            table=Base.metadata.tables[name]
            query=select(table)
            if name=='activity_knowledge_versions':query=query.order_by(table.c.version_no)
            rows=[dict(row) for row in source.execute(query).mappings()]
            if name=='activity_knowledge_versions':
                for row in rows:
                    versions.append((row['id'],row['status'],row['updated_at']))
                    row['status']='VALIDATED'
            # Break only nullable self/circular references during this transaction.
            fields={'activities':['current_version_id','merged_into_id']}.get(name,[])
            for row in rows:
                values={key:row[key] for key in fields if row[key] is not None}
                if values:deferred.append((table,row['id'],values))
                for key in fields:row[key]=None
            if name=='document_sections':
                pending=rows[:];inserted=set()
                while pending:
                    batch=[r for r in pending if r['parent_id'] is None or r['parent_id'] in inserted]
                    if not batch:raise ValueError('Cyclic or missing section parent')
                    target.execute(table.insert(),batch)
                    inserted.update(r['id'] for r in batch)
                    pending=[r for r in pending if r['id'] not in inserted]
            elif rows:target.execute(table.insert(),rows)
            counts[name]=len(rows)
        version_table=Base.metadata.tables['activity_knowledge_versions']
        for key,status,timestamp in versions:
            target.execute(update(version_table).where(version_table.c.id==key).values(status=status,updated_at=timestamp))
        for table,key,values in deferred:
            # Core update otherwise runs TimestampMixin.onupdate and breaks the
            # byte-for-byte reviewed snapshot's timestamps.
            original_time=source.scalar(select(table.c.updated_at).where(table.c.id==key))
            target.execute(update(table).where(table.c.id==key).values(**values,updated_at=original_time))
        documents=Base.metadata.tables['document_versions']
        for row in source.execute(select(documents.c.id,documents.c.section_parser_version,documents.c.updated_at)).mappings():
            if row['section_parser_version'] is not None:
                target.execute(update(documents).where(documents.c.id==row['id']).values(
                    section_parser_version=row['section_parser_version'],updated_at=row['updated_at']))
        for name in TABLES:
            if digest(source,name)!=digest(target,name):raise ValueError(f'Knowledge mismatch: {name}')
        if preserved!=digest(target,'status_holdings'):raise ValueError('User holdings changed')
        return {'counts':counts,'source_tables_equal':SOURCES,'knowledge_equal':True,'holdings_unchanged':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-database',required=True)
    parser.add_argument('--target-database',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.source_database==args.target_database:parser.error('Source and target must differ')
    if args.output.exists():parser.error('Keep previous evidence; choose a new output')
    url=make_url(Settings.from_env().database_url)
    result=promote(create_engine(url.set(database=args.source_database)),create_engine(url.set(database=args.target_database)))
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result))

if __name__=='__main__':main()
