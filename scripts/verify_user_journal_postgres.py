"""Isolated PostgreSQL restore/replay exercise; never modifies the source DB."""
from argparse import ArgumentParser
from datetime import UTC,datetime,date
import json,os,subprocess
from pathlib import Path
from sqlalchemy import create_engine,select,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from journeyplus.config import Settings
from journeyplus.models import StatusHolding,AgentWaitGoal
from journeyplus.knowledge.user_journal import enable_journal,export_operations,replay_operations,snapshot,configure_user_data
from journeyplus.product.api import create_product_app


def business_state(factory):
    with factory() as session:
        return {model.__tablename__:{str(row.id):snapshot(model,row) for row in session.scalars(select(model))}
                for model in (StatusHolding,AgentWaitGoal)}


def main():
    parser=ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();base=make_url(Settings.from_env().database_url)
    if args.source==base.database or not args.source.startswith(('journeyplus_knowledge_','journeyplus_eval_')):
        parser.error('Source must be an explicitly isolated validation database')
    out=Path(args.output).resolve()
    if not out.is_relative_to((Path.cwd()/'.secrets').resolve()):parser.error('Output must be private under .secrets')
    out.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(UTC).strftime('%Y%m%d_%H%M%S')
    names=['journeyplus_eval_journal_'+suffix+'_'+stamp for suffix in ('writes','replay')]
    docker=['/usr/local/bin/docker','exec','journeyplus-postgres-1']
    dump=out/'baseline.dump'
    with dump.open('wb') as file:
        subprocess.run([*docker,'pg_dump','-U',base.username,'-Fc','-d',args.source],stdout=file,stderr=subprocess.PIPE,check=True)
    dump.chmod(0o600)
    admin=create_engine(base.set(database='postgres'),isolation_level='AUTOCOMMIT');factories=[]
    for name in names:
        with admin.connect() as conn:conn.execute(text('CREATE DATABASE '+conn.dialect.identifier_preparer.quote(name)))
        with dump.open('rb') as file:
            subprocess.run([docker[0],'exec','-i',docker[2],'pg_restore','-U',base.username,'-d',name,'--exit-on-error'],stdin=file,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        env={**os.environ,'JOURNEYPLUS_DATABASE_URL':base.set(database=name).render_as_string(hide_password=False)}
        # Empty journal roundtrip; populated journal downgrade is intentionally refused.
        for revision in ('head','0023_wait_seen_candidates','head'):
            subprocess.run(['.venv/bin/alembic','upgrade' if revision=='head' else 'downgrade',revision],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        factories.append(sessionmaker(create_engine(base.set(database=name)),expire_on_commit=False))
    source,replay=factories
    baseline=business_state(source);assert baseline==business_state(replay)
    enable_journal(source)
    with source.begin() as session:
        row=session.scalar(select(StatusHolding).order_by(StatusHolding.program_key));assert row is not None
        changed_id=row.id;row.valid_until=date(2030,1,31);row.revision+=1
        from journeyplus.knowledge.models import MembershipProgram,MembershipTier
        occupied=[v for v in session.scalars(select(StatusHolding.program_id)) if v]
        program,tier=session.execute(select(MembershipProgram,MembershipTier).join(MembershipTier,MembershipTier.program_id==MembershipProgram.id)
            .where(MembershipProgram.id.not_in(occupied)).order_by(MembershipProgram.canonical_key,MembershipTier.canonical_key).limit(1)).one()
        session.add(StatusHolding(program_key=program.canonical_key,tier_key=tier.canonical_key,
            program_display_name=program.display_name,tier_display_name=tier.display_name,
            program_id=program.id,tier_id=tier.id,identity_status='CONFIRMED'))
        # These are copied validation records, never the user's source records.
        for goal in session.scalars(select(AgentWaitGoal).where(AgentWaitGoal.status.in_(['ACTIVE','RESULT_PENDING','NEEDS_RECONFIRMATION']))):
            goal.status='COMPLETED';goal.ended_at=datetime.now(UTC);goal.revision+=1
        session.flush()
        goal=AgentWaitGoal(status='ACTIVE',query={'free_only':True,'use_saved_holdings':True},conditions_schema_version=2)
        session.add(goal);session.flush();gid=goal.id
    with source.begin() as session:
        goal=session.get(AgentWaitGoal,gid);goal.status='NEEDS_RECONFIRMATION';goal.revision+=1
    with source() as session:operations=export_operations(session)
    assert len(operations)>=4
    journal=out/'user-operations.json';journal.write_text(json.dumps(operations,ensure_ascii=False,indent=2));journal.chmod(0o600)
    expected=business_state(source)
    configure_user_data(replay,'rollback')
    client=TestClient(create_product_app(replay,knowledge_read_mode='rollback'))
    blocked=client.post('/v1/status-holdings',json={});assert blocked.status_code==503
    assert client.get('/v2/rollout').json()['user_writes_paused']
    with replay.begin() as session:first=replay_operations(session,operations)
    assert business_state(replay)==expected
    with replay.begin() as session:second=replay_operations(session,operations)
    assert second=={'applied':0,'duplicates':len(operations)}
    assert business_state(replay)==expected
    # Deliberate divergent state must reject the entire transaction.
    configure_user_data(replay,'unified')
    with replay.begin() as session:
        row=session.get(StatusHolding,changed_id);row.revision+=1
    before_conflict=business_state(replay)
    from copy import deepcopy
    from uuid import uuid4
    conflicted=deepcopy(operations)
    for operation in conflicted:
        if operation['entity_id']==str(changed_id):operation['operation_id']=str(uuid4())
    try:
        with replay.begin() as session:replay_operations(session,conflicted)
    except ValueError as exc:assert 'diverged' in str(exc)
    else:raise AssertionError('Divergent user state was overwritten')
    assert before_conflict==business_state(replay)
    result={'source_read_only':args.source,'isolated_databases':names,'baseline_entities':{k:len(v) for k,v in baseline.items()},
            'journal_operations':len(operations),'first_replay':first,'repeat_replay':second,'business_state_equal':True,
            'conflict_atomic_rejection':True,'http_write_fence':True,'migration_roundtrip':'0023 -> 0024 -> 0023 -> 0024',
            'limitations':['Replay retains the additive catalogue/knowledge tables; missing foreign keys fail rather than being guessed.',
                            'Stop and drain API/worker processes before a real checkpoint; this exercise uses private copies.']}
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
    for factory in factories:factory.kw['bind'].dispose()
    admin.dispose()


if __name__=='__main__':main()
