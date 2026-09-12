"""Read-only formal-data audit; tool artifacts live in a disposable SQLite DB.

Run from repository root: .venv/bin/python doc/agent-workflow-read-adaptation/audit_read_chain.py
No AI calls, production mutations, migrations, or app lifespan/maintenance.
"""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import tempfile
from uuid import UUID

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from journeyplus.config import Settings
from journeyplus.models import Base, StatusEvent, FactSetRecord, BriefRecord, DocumentVersion
from journeyplus.agent.adapters.workflow_knowledge import WorkflowKnowledgePort, graph_state, identity_id
from journeyplus.agent.adapters.workflow_routes import WorkflowRouteService
from journeyplus.knowledge.routes import RouteQuery
from journeyplus.membership.normalization import normalize_tier
from journeyplus.product.api import create_product_app
from tests.test_agent_workflow_reads import context, call

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).with_name('audit-verification.json')
engine = create_engine(Settings.from_env().database_url)
assert engine.dialect.name=='postgresql', 'This audit expects the configured formal PostgreSQL database'
statements=[]
@event.listens_for(engine,'begin')
def read_only(connection):
    connection.exec_driver_sql('SET TRANSACTION READ ONLY')
@event.listens_for(engine,'before_cursor_execute')
def capture(connection,cursor,statement,parameters,ctx,many):
    statements.append(statement)
factory=sessionmaker(engine,expire_on_commit=False)
port=WorkflowKnowledgePort(factory)


def fingerprint():
    with port.read() as session:
        session.execute(text("SET TIME ZONE 'UTC'"))
        tables=session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
        result={}
        for table in tables:
            rows=session.execute(text('SELECT to_jsonb(t)::text FROM "'+table+'" t ORDER BY to_jsonb(t)::text')).scalars().all()
            result[table]={'count':len(rows),'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest()}
        return result


before=fingerprint()
report={'database':engine.url.database,'formal_transactions_read_only':True,'model_calls':0}
with port.read() as session:
    activity=session.scalar(select(StatusEvent).where(StatusEvent.program.ilike('%Flying%')))
    assert activity and activity.current_fact_set_id
    record=session.get(FactSetRecord,activity.current_fact_set_id)
    brief=session.get(BriefRecord,activity.current_brief_id)
    raw=record.facts
    expected_brief=brief.content
    detail=port.activity_reader(session).detail(activity.id,record.id)
    fields=set(raw)-{'status_mappings','application_routes'}
    assert all(detail['facts'][key]==raw[key] for key in fields)
    projected=detail['options'][-1]['mappings']
    assert len(projected)==len(raw['status_mappings'])
    assert all(all(projected[i][k]==v for k,v in m.items()) for i,m in enumerate(raw['status_mappings']))
    assert all(all(detail['options'][i][k]==v for k,v in r.items()) for i,r in enumerate(raw['application_routes']))
    assert detail['briefs'][0]['content']==expected_brief
    docs={str(d.id):d.normalized_body for d in session.scalars(select(DocumentVersion))}
    assert {s['document_version_ref'] for s in detail['sources']}==set(docs)
    state=graph_state(session)
    expected_claims={f'official:{record.id}:{i}:{j}' for i,m in enumerate(raw['status_mappings']) for j,_ in enumerate(m['source_tiers'])
                     if m['availability']!='UNAVAILABLE'}
    assert {c.contribution_id for c in state.contributions}==expected_claims
    expected=set()
    for claim in state.contributions:
        for i,route in enumerate(raw['application_routes']):
            quotes=[p for p in route['prices'] if not p['target_tier'] or normalize_tier(p['target_tier'])==normalize_tier(claim.target_tier)]
            if quotes and all(p['availability']=='UNAVAILABLE' for p in quotes):continue
            expected.add((claim.contribution_id,i))
    roots=[identity_id('tier',node.id) for node in state.nodes.values()]
    actual=set();price_checks=0
    for offset in range(0,len(roots),20):
        result=WorkflowRouteService(session).query(RouteQuery(starting_tier_ids=roots[offset:offset+20],use_saved_holdings=False),deadline_seconds=30)
        assert result['coverage']['stopped_reason'] is None
        for step in result['server_steps'].values():
            index=int(step['option_ref'].removeprefix('route-'))
            actual.add((step['claim_ref'],index))
            mapping_index=int(step['claim_ref'].rsplit(':',2)[1])
            assert step['mapping_ref']==f'mapping-{mapping_index}'
            assert step['action_link']==(raw['application_routes'][index]['action_link'] or raw['action_link']['value'])
            for price in step['fees']+step['conditional_items']:
                price_index=int(price['ref'].rsplit('/price-',1)[1])
                original=raw['application_routes'][index]['prices'][price_index]
                assert (price['amount'],price['currency'],price['raw_text'])==(original['amount'],original['currency'],original['raw_text'])
                assert original['availability']!='UNAVAILABLE'
                price_checks+=1
    assert actual==expected
    report['content_comparison']={'fact_fields_including_metadata':len(fields),'mappings':len(projected),
        'application_routes':len(raw['application_routes']),'price_records':sum(len(r['prices']) for r in raw['application_routes']),
        'brief_exact_match':True,'source_documents':len(docs),'graph_claims':len(expected_claims),
        'route_region_variants':len(expected),'missing_variants':0,'invented_variants':0,'price_reference_checks':price_checks}
    aid,fid=activity.id,record.id
    report['known_incoming_content_issue']={'scope':'Existing stored brief; unchanged by this audit',
        'stored_excerpt':next((p['text'] for p in expected_brief.get('key_points',[]) if 'USD 399（阿根廷' in p['text']),None),
        'details':'Review the stored excerpt against the structured regional prices. Read fidelity does not validate generated prose.'}

with tempfile.TemporaryDirectory(prefix='journeyplus-audit-artifacts-') as tmp:
    artifacts=create_engine('sqlite:///'+str(Path(tmp)/'artifacts.db'),connect_args={'check_same_thread':False})
    Base.metadata.create_all(artifacts)
    runtime,store,ctx=context(sessionmaker(artifacts,expire_on_commit=False),factory)
    overview=call(runtime,ctx,'activity.read',{'selector':{'ref':f'activity:{aid}@{fid}'}})
    item=overview.data['activities'][0]
    full_brief=call(runtime,ctx,'activity.read',{'selector':{'ref':item['ref']},'section_refs':[item['brief_section_ref']]})
    assert full_brief.data['sections'][0]['payload']['briefs'][0]['content']==expected_brief
    chunk_count=0
    for doc_id,body in docs.items():
        ref='document:'+doc_id+':0';parts=[]
        while ref:
            result=call(runtime,ctx,'activity.read',{'selector':{'ref':item['ref']},'section_refs':[ref]})
            src=result.data['activities'][0]['evidence']['source_sections_ref']
            chunk=store.artifacts.read(ctx.workspace_id,src)['payload']['snippets'][0]
            parts.append(chunk['text']);ref=chunk['next_ref'];chunk_count+=1
        assert ''.join(parts)==body
    report['progressive_read']={'overview_bytes':len(overview.model_dump_json().encode()),'brief_section_exact':True,
        'document_chunks':chunk_count,'all_normalized_documents_reassembled_exactly':True}
    scenarios=[]
    for program,tier,residency,budget in [('Air Canada Aeroplan','Elite 50K',None,None),
        ('Air Canada Aeroplan','Elite 50K','希腊','250'),('United Airlines MileagePlus','Premier 1K',None,None)]:
        query={'sources':{'mode':'explicit','identities':[{'program_name':program,'tier_name':tier}]},'target':{'program_name':'Flying Blue'}}
        if residency:query['constraints']={'residency':residency,'max_amount':budget,'currency':'EUR'}
        result=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':query,'limit':1})
        rows=list(result.data['candidates']);cursor=result.next_cursor
        while cursor:
            result=call(runtime,ctx,'routes.evaluate',{'operation':'search','query_ref':result.data['query_ref'],'cursor':cursor,'limit':1})
            rows.extend(result.data['candidates']);cursor=result.next_cursor
        assert len({r['ref'] for r in rows})==len(rows) and rows
        if residency:
            assert len(rows)==1 and rows[0]['cost']['totals'][0]['amount']=='199'
            assert rows[0]['cost']['totals'][0]['currency']=='EUR'
        if program.startswith('United'):
            assert len(rows)==2 and all(r['constraint_match']=='UNKNOWN' for r in rows)
        inspected=call(runtime,ctx,'routes.evaluate',{'operation':'inspect','route_refs':[rows[0]['ref']]})
        selected_step=inspected.data['steps'][0]
        material=call(runtime,ctx,'activity.read',{'selector':{'ref':selected_step['ref']},'view':'detail'})
        root=material.data['activities'][0]['material_ref']
        section=call(runtime,ctx,'activity.read',{'selector':{'ref':item['ref']},
            'section_refs':[root+'#section:mapping-'+selected_step['mapping_ref']]})
        assert section.data['sections'][0]['payload']['mapping']['ref']==selected_step['mapping_ref']
        scenarios.append({'program':program,'tier':tier,'residency':residency,'budget_eur':budget,
            'candidates':len(rows),'constraint_match':[r['constraint_match'] for r in rows],
            'pagination_no_missing_or_duplicate':True,'inspect_to_mapping_section':True})
    report['tool_scenarios']=scenarios
    artifacts.dispose()

# A plain client does not start lifespan maintenance or create Agent workspaces.
client=TestClient(create_product_app(factory),raise_server_exceptions=False)
page=client.get('/opportunities/'+str(fid))
response=client.get('/v1/match-opportunities/'+str(fid))
assert page.status_code==response.status_code==200
assert response.json()['brief']==expected_brief
client.close()
report['opportunity_http']={'page':page.status_code,'data':response.status_code,'brief_exact_match':True}
after=fingerprint()
assert before==after
baseline=ROOT/'doc/database-archives/20260912T051216Z-formal-original-model/verification.json'
report['formal_data_unchanged']=before==after
report['formal_data_matches_cutover_archive']=after==json.loads(baseline.read_text())['after']['tables']
report['production_mutation_statements']=[s.split()[0] for s in statements if s.lstrip().upper().startswith(('INSERT ','UPDATE ','DELETE ','ALTER ','CREATE ','DROP ','TRUNCATE '))]
assert not report['production_mutation_statements']
OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
engine.dispose()
