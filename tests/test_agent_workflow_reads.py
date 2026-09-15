"""Run the real tool registry against an original-schema-only knowledge database."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text, event, select
from sqlalchemy.orm import sessionmaker

from journeyplus.agent.composition import compose_business
from journeyplus.agent.harness.contracts import ExecutionContext
from journeyplus.agent.adapters.workflow_knowledge import WorkflowKnowledgePort
from journeyplus.models import ArticleOpportunityRecord, DocumentVersion
from tests.test_candidate_routes import _mapping_opportunity
from tests.test_harness_runtime import FakeModel


@pytest.fixture
def original_factory(tmp_path):
    baseline = Path(__file__).parents[1] / 'doc/database-archives/20260912T042852Z-original-aiworkflow/legacy-source/src/journeyplus/models.py'
    spec = importlib.util.spec_from_file_location('workflow_baseline_models',baseline)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    engine = create_engine('sqlite:///'+str(tmp_path/'original.sqlite'),connect_args={'check_same_thread':False})
    module.Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE source_items ADD COLUMN document_role varchar(30) DEFAULT 'OTHER'"))
        c.execute(text('ALTER TABLE document_versions ADD COLUMN section_parser_version varchar(100)'))
        c.execute(text("ALTER TABLE status_holdings ADD COLUMN user_id CHAR(32) NOT NULL DEFAULT '00000000000000000000000000000001'"))
    statements = []
    event.listen(engine,'before_cursor_execute',lambda conn,cursor,statement,params,context,many:statements.append(statement))
    factory = sessionmaker(engine,expire_on_commit=False)
    factory.statements = statements
    yield factory
    engine.dispose()


def context(user_factory, knowledge_factory):
    runtime,store = compose_business(user_factory,FakeModel([]),read_factory=knowledge_factory)
    # Keep user-route reads on the original schema as in the actual deployment;
    # only workspace artifacts use isolated test storage.
    runtime.services['route_queries'].user_data = WorkflowKnowledgePort.user_data(knowledge_factory)
    w = store.create()
    ctx = ExecutionContext(w['id'],str(uuid4()),'call','local-user',monotonic()+60,
        asyncio.Event(),store.artifacts,store,runtime.services)
    return runtime,store,ctx


def call(runtime,ctx,name,arguments):
    ctx.call_id = str(uuid4())
    validated,_ = runtime.ports.registry.validate(name,arguments)
    result = asyncio.run(runtime.ports.registry.execute(validated,ctx))
    assert result.error is None, result.model_dump(mode='json')
    return result


def seed(factory, **changes):
    args = dict(slug=str(uuid4()),source_program='Marriott Bonvoy',source_tier='Platinum',
        target_program='Example Rewards',target_tier='Gold',amount=49,challenge='No challenge')
    args.update(changes)
    with factory.begin() as session:
        row = _mapping_opportunity(session,**args)
        identity = row.id
    return identity


def test_original_schema_catalog_routes_inspect_and_progressive_materials(original_factory,session_factory):
    identity = seed(original_factory)
    runtime,store,ctx = context(session_factory,original_factory)
    assert runtime.services['knowledge'].availability()['status']=='AVAILABLE'
    directory = call(runtime,ctx,'catalog.lookup',{'query':'Marriott Bonvoy Platinum'})
    tier_ref = next(c['ref'] for c in directory.data['candidates'] if c['ref'].startswith('tier:'))
    query = {'sources':{'mode':'explicit','identities':[{'ref':tier_ref}]},'target':{'program_name':'Example Rewards'}}
    routes = call(runtime,ctx,'routes.evaluate',{'operation':'search','query':query})
    assert routes.data['candidates']
    inspected = call(runtime,ctx,'routes.evaluate',{'operation':'inspect','route_refs':routes.data['route_refs'][:1]})
    assert inspected.data['steps'][0]['paid'] is True
    assert 'fees' not in inspected.data['steps'][0]
    assert inspected.data['steps'][0]['mapping_ref']=='mapping-0'
    assert inspected.data['steps'][0]['brief_url']
    assert 'eligibility' not in inspected.data['candidates'][0]
    overview = call(runtime,ctx,'activity.read',{'selector':{'query':'Example Rewards'}})
    item = overview.data['activities'][0]
    assert item['ref'].startswith('activity:'+str(identity)+'@')
    assert 'facts' not in item and 'options' not in item
    assert item['brief_url'].startswith(f'/knowledge?activity_id={identity}&version_ref=')
    detailed = call(runtime,ctx,'activity.read',{'selector':{'ref':item['ref']},'view':'detail'})
    mapping = detailed.data['activities'][0]['options'][-1]['mapping_index'][0]
    section = call(runtime,ctx,'activity.read',{'selector':{'ref':item['ref']},'section_refs':[mapping['section_ref']]})
    assert section.data['sections'][0]['payload']['mapping']['from_program']=='Marriott Bonvoy'
    evidence = call(runtime,ctx,'activity.read',{'selector':{'ref':item['ref']},'view':'evidence'})
    src = evidence.data['activities'][0]['evidence']['catalog'][0]
    assert evidence.data['activities'][0]['evidence']['source_document_count']==1
    assert 'source_sections_ref' not in evidence.data['activities'][0]['evidence']
    original = call(runtime,ctx,'activity.read',{'selector':{'ref':item['ref']},'view':'evidence','section_refs':[src['section_ref']]})
    assert original.data['documents'][0]['complete'] is True
    serialized = json.dumps(original_factory.statements).lower()
    assert 'membership_programs' not in serialized and 'application_options' not in serialized


def test_unavailable_tier_price_never_becomes_payable(original_factory,session_factory):
    identity = seed(original_factory)
    with original_factory.begin() as s:
        row=s.get(ArticleOpportunityRecord,identity)
        facts=json.loads(json.dumps(row.facts))
        price=facts['application_routes'][0]['prices'][0]
        price.update(target_tier='Gold',amount=None,availability='UNAVAILABLE')
        facts['application_routes'][0]['prices'].append({**price,'target_tier':'Silver','amount':'1','availability':'AVAILABLE'})
        row.facts=facts
    runtime,_,ctx=context(session_factory,original_factory)
    result=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':{
        'sources':{'mode':'explicit','identities':[{'program_name':'Marriott Bonvoy','tier_name':'Platinum'}]}}})
    assert len(result.data['candidates'])==1  # Regional availability is auxiliary, mapping is retained.
    assert 'cost' not in result.data['candidates'][0]


def test_regional_prices_are_not_global_totals_and_filters_are_preserved(original_factory,session_factory):
    identity=seed(original_factory)
    with original_factory.begin() as s:
        row=s.get(ArticleOpportunityRecord,identity)
        facts=json.loads(json.dumps(row.facts))
        facts['application_routes'][0]['region']='Argentina and Chile'
        row.facts=facts
    runtime,store,ctx=context(session_factory,original_factory)
    query={'sources':{'mode':'explicit','identities':[{'program_name':'Marriott Bonvoy','tier_name':'Platinum'}]}}
    result=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':query})
    assert result.data['candidates'][0]['paid'] is True
    assert 'cost' not in result.data['candidates'][0]
    inspected=call(runtime,ctx,'routes.evaluate',{'operation':'inspect','route_refs':result.data['route_refs']})
    assert 'conditional_items' not in inspected.data['steps'][0]
    filtered=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':{**query,'constraints':{'free_only':True}}})
    assert filtered.status=='EMPTY' and not filtered.data['candidates']


def test_saved_original_holdings_and_snapshot_do_not_require_new_columns(original_factory,session_factory):
    seed(original_factory)
    with original_factory.begin() as s:
        s.execute(text("INSERT INTO status_holdings (id,program_key,tier_key,program_display_name,tier_display_name,created_at,updated_at) VALUES (:id,'marriott bonvoy','platinum','Marriott Bonvoy','Platinum',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"),{'id':uuid4().hex})
    runtime,_,ctx=context(session_factory,original_factory)
    args={'operation':'search','query':{'sources':{'mode':'saved'}}}
    result=call(runtime,ctx,'routes.evaluate',args)
    assert result.data['candidates']
    from journeyplus.agent.services.snapshots import snapshot_for
    from journeyplus.agent.tools.contracts import RoutesInput
    assert snapshot_for('routes.evaluate',runtime.services['knowledge'],original_factory)(RoutesInput(**args),ctx)


def test_pagination_is_pinned_and_foreign_sections_rejected(original_factory,session_factory):
    first=seed(original_factory,target_program='Example One')
    seed(original_factory,target_program='Example Two')
    runtime,_,ctx=context(session_factory,original_factory)
    page=call(runtime,ctx,'activity.read',{'selector':{'query':'Example'},'limit':1})
    assert page.next_cursor
    seed(original_factory,target_program='Example Three')
    next_page=call(runtime,ctx,'activity.read',{'selector':{'query':'Example'},'limit':1,'cursor':page.next_cursor})
    assert next_page.coverage['total']==2 and next_page.next_cursor is None
    ref=page.data['activities'][0]['ref']
    other=next_page.data['activities'][0]['ref']
    detail=call(runtime,ctx,'activity.read',{'selector':{'ref':ref},'view':'detail'})
    section=detail.data['activities'][0]['options'][-1]['mapping_index'][0]['section_ref']
    validated,_=runtime.ports.registry.validate('activity.read',{'selector':{'ref':other},'section_refs':[section]})
    result=asyncio.run(runtime.ports.registry.execute(validated,ctx))
    assert result.error is not None


def test_source_text_is_never_loaded_for_overview(original_factory,session_factory):
    seed(original_factory)
    with original_factory.begin() as s:
        document=s.scalar(select(DocumentVersion))
        document.raw_body='RAW_SNAPSHOT_SENTINEL'*1000
        document.normalized_body='NORMALIZED_SNAPSHOT_SENTINEL'*1000
    runtime,_,ctx=context(session_factory,original_factory)
    original_factory.statements.clear()
    result=call(runtime,ctx,'activity.read',{'selector':{'query':'Example'},'view':'overview'})
    encoded=json.dumps(result.model_dump(mode='json'))
    assert 'SNAPSHOT_SENTINEL' not in encoded
    # Existing workflow graph readers may inspect archived documents for parsing,
    # but none of that body is loaded into returned materials/model context.
    evidence=call(runtime,ctx,'activity.read',{'selector':{'ref':result.data['activities'][0]['ref']},'view':'evidence'})
    assert 'SNAPSHOT_SENTINEL' not in json.dumps(evidence.model_dump(mode='json'))


def test_multistep_endpoints_and_known_fees_use_existing_result_contract(original_factory,session_factory):
    seed(original_factory,amount=20)
    seed(original_factory,source_program='Example Rewards',source_tier='Gold',
         target_program='Final Rewards',target_tier='Platinum',amount=30)
    runtime,_,ctx=context(session_factory,original_factory)
    result=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':{
        'sources':{'mode':'explicit','identities':[{'program_name':'Marriott Bonvoy','tier_name':'Platinum'}]},
        'target':{'program_name':'Final Rewards'}}})
    assert len(result.data['candidates'])==1
    route=result.data['candidates'][0]
    assert route['step_count']==2 and route['to'].casefold()=='final rewards platinum'
    assert route['paid'] is True and 'cost' not in route


def test_official_historical_factset_never_uses_current_brief(original_factory,session_factory):
    from journeyplus.models import StatusEvent,FactSetRecord,BriefRecord
    from journeyplus.contracts import Brief
    source=seed(original_factory)
    with original_factory.begin() as s:
        article=s.get(ArticleOpportunityRecord,source)
        event=StatusEvent(created_from_key=str(uuid4()),program='Official Rewards',summary='Current summary')
        s.add(event);s.flush()
        facts=json.loads(json.dumps(article.facts));facts['event_id']=str(event.id)
        records=[]
        for number in (1,2):
            record=FactSetRecord(event_id=event.id,version=number,schema_version='5',facts=facts)
            s.add(record);s.flush()
            content=Brief(fact_set_id=record.id,title=f'Version {number}',title_fact_keys=['what_happened'],
                summary=f'Brief {number}',summary_fact_keys=['what_happened'])
            brief=BriefRecord(fact_set_id=record.id,version=1,schema_version='1',content=content.model_dump(mode='json'))
            s.add(brief);s.flush();records.append(record)
        event.current_fact_set_id=records[-1].id;event.current_brief_id=brief.id
        ref=f'activity:{event.id}@{records[0].id}'
    runtime,_,ctx=context(session_factory,original_factory)
    result=call(runtime,ctx,'activity.read',{'selector':{'ref':ref}})
    assert result.data['activities'][0]['title']=='Version 1'
    assert result.data['activities'][0]['summary']['summary']=='Brief 1'
    history=call(runtime,ctx,'activity.read',{'selector':{'ref':ref},'view':'changes'})
    assert len(history.data['activities'][0]['history']['versions'])==2


def test_complete_original_and_requested_price_aspect(original_factory,session_factory):
    seed(original_factory)
    with original_factory.begin() as s:
        doc=s.scalar(select(DocumentVersion))
        doc.normalized_body='start-'+'x'*13000+'-end'
    runtime,store,ctx=context(session_factory,original_factory)
    overview=call(runtime,ctx,'activity.read',{'selector':{'query':'Example Rewards'}})
    ref=overview.data['activities'][0]['ref']
    directory=call(runtime,ctx,'activity.read',{'selector':{'ref':ref},'aspects':['price']})
    requested=directory.data['activities'][0]['evidence']
    assert any(row['field']=='prices' for row in requested['facts'])
    chunk_ref=requested['catalog'][0]['section_ref']
    result=call(runtime,ctx,'activity.read',{'selector':{'ref':ref},'view':'original','section_refs':[chunk_ref]})
    assert result.data['documents'][0]['text']=='start-'+'x'*13000+'-end'
    assert result.data['documents'][0]['complete'] is True



def test_original_read_port_does_not_recreate_missing_tables(original_factory,session_factory):
    with original_factory() as s:
        before=s.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")).scalars().all()
    runtime,_,ctx=context(session_factory,original_factory)
    assert runtime.services['knowledge'].availability()['status']=='UNAVAILABLE'
    with original_factory() as s:
        assert before==s.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")).scalars().all()


def test_conditional_mapping_is_disclosed_instead_of_an_empty_result(original_factory,session_factory):
    identity=seed(original_factory)
    with original_factory.begin() as s:
        row=s.get(ArticleOpportunityRecord,identity)
        facts=json.loads(json.dumps(row.facts))
        facts['status_mappings'][0].update(availability='CONDITIONAL',conditions='Restricted to eligible residents')
        row.facts=facts
    runtime,_,ctx=context(session_factory,original_factory)
    query={'sources':{'mode':'explicit','identities':[{'program_name':'Marriott Bonvoy','tier_name':'Platinum'}]}}
    result=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':query})
    assert result.status=='OK' and len(result.data['route_refs'])==1
    assert result.data['candidates'][0]['constraint_match']=='SATISFIES'
    inspected=call(runtime,ctx,'routes.evaluate',{'operation':'inspect','route_refs':result.data['route_refs']})
    assert inspected.data['steps'][0]['availability']=='CONDITIONAL'
    assert 'constraint_checks' not in inspected.data['steps'][0]
    detail=call(runtime,ctx,'activity.read',{'selector':{'query':'Example Rewards'},'view':'detail'})
    activity=detail.data['activities'][0]
    section=activity['options'][-1]['mapping_index'][0]['section_ref']
    expanded=call(runtime,ctx,'activity.read',{'selector':{'ref':activity['ref']},'section_refs':[section]})
    assert 'Restricted to eligible residents' in json.dumps(expanded.data)


def test_explicit_residency_retains_other_regions_without_mixing_prices(original_factory,session_factory):
    identity=seed(original_factory)
    with original_factory.begin() as s:
        row=s.get(ArticleOpportunityRecord,identity)
        facts=json.loads(json.dumps(row.facts))
        route=facts['application_routes'][0];route['region']='Greece';route['scope']='Greece'
        gold={**route['prices'][0],'target_tier':'Gold'}
        route['prices']=[{**gold,'target_tier':'Silver','amount':'1'},gold]
        foreign=json.loads(json.dumps(route));foreign['region']='Argentina, Chile';foreign['scope']='South America';foreign['prices'][1]['amount']='199'
        facts['application_routes'].append(foreign);row.facts=facts
    runtime,_,ctx=context(session_factory,original_factory)
    query={'sources':{'mode':'explicit','identities':[{'program_name':'Marriott Bonvoy','tier_name':'Platinum'}]},
           'constraints':{'free_only':False}}
    result=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':query})
    assert len(result.data['route_refs'])==1 and result.status=='OK'
    inspected=call(runtime,ctx,'routes.evaluate',{'operation':'inspect','route_refs':result.data['route_refs']})
    assert len(inspected.data['steps'])==1 and inspected.data['steps'][0]['paid']
    assert 'application_scope' not in inspected.data['steps'][0]
    detail=call(runtime,ctx,'activity.read',{'selector':{'query':'Example Rewards'},'view':'detail'})
    assert 'Greece' in json.dumps(detail.data) and '199' in json.dumps(detail.data)


def test_region_prose_and_mixed_challenge_are_not_assumed_proven(original_factory,session_factory):
    identity=seed(original_factory,challenge='No challenge for Silver; Gold requires a status challenge')
    with original_factory.begin() as s:
        row=s.get(ArticleOpportunityRecord,identity)
        facts=json.loads(json.dumps(row.facts))
        facts['application_routes'][0]['region']='All countries except Greece'
        row.facts=facts
    runtime,_,ctx=context(session_factory,original_factory)
    result=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':{
        'sources':{'mode':'explicit','identities':[{'program_name':'Marriott Bonvoy','tier_name':'Platinum'}]},
        'constraints':{'free_only':False}}})
    assert result.status=='OK'
    assert 'eligibility' not in result.data['candidates'][0]
    assert result.data['candidates'][0]['paid'] is True


def test_conflicting_explicit_version_cannot_override_a_pinned_reference(original_factory,session_factory):
    identity=seed(original_factory)
    runtime,_,ctx=context(session_factory,original_factory)
    overview=call(runtime,ctx,'activity.read',{'selector':{'query':'Example Rewards'}})
    args={'selector':{'ref':overview.data['activities'][0]['ref']},'version_ref':str(uuid4())}
    validated,_=runtime.ports.registry.validate('activity.read',args)
    result=asyncio.run(runtime.ports.registry.execute(validated,ctx))
    assert result.error.code=='STALE_REFERENCE'


def test_original_opportunity_page_data_does_not_require_unified_holding_fields(original_factory):
    from fastapi.testclient import TestClient
    from journeyplus.product.api import create_product_app
    identity=seed(original_factory)
    # Do not enter lifespan: this is an isolated read endpoint test, not a
    # maintenance/Agent-storage migration test.
    from journeyplus.accounts import UserAccount,LoginSession,create_account
    from journeyplus.user_scope import OWNER_ID
    UserAccount.metadata.create_all(original_factory.kw['bind'],tables=[UserAccount.__table__,LoginSession.__table__])
    create_account(original_factory,'owner','Test-product-login-2026',identity=OWNER_ID)
    client=TestClient(create_product_app(original_factory))
    assert client.post('/auth/login',json={'username':'owner','password':'Test-product-login-2026'}).status_code==200
    assert client.get('/opportunities/'+str(identity)).status_code==200
    response=client.get('/v1/match-opportunities/'+str(identity))
    assert response.status_code==200
    assert response.json()['opportunity_id']==str(identity)


def test_selected_brief_pointer_is_authoritative_within_same_factset(original_factory):
    from journeyplus.models import StatusEvent,FactSetRecord,BriefRecord
    from journeyplus.contracts import Brief
    from journeyplus.agent.adapters.workflow_knowledge import WorkflowActivityReader
    source=seed(original_factory)
    with original_factory.begin() as s:
        event=StatusEvent(created_from_key=str(uuid4()),program='Official Rewards',summary='summary')
        s.add(event);s.flush()
        facts=json.loads(json.dumps(s.get(ArticleOpportunityRecord,source).facts));facts['event_id']=str(event.id)
        record=FactSetRecord(event_id=event.id,version=1,schema_version='5',facts=facts)
        s.add(record);s.flush();event.current_fact_set_id=record.id
        for version in (1,2):
            content=Brief(fact_set_id=record.id,title=f'Brief {version}',title_fact_keys=['what_happened'],
                summary=f'Summary {version}',summary_fact_keys=['what_happened'])
            brief=BriefRecord(fact_set_id=record.id,version=version,schema_version='1',content=content.model_dump(mode='json'))
            s.add(brief);s.flush()
            if version==1:event.current_brief_id=brief.id
        event_id=event.id
    with original_factory() as s:
        assert WorkflowActivityReader(s).detail(event_id)['name']=='Brief 1'


def test_simple_waiting_uses_same_routes_and_rejects_old_constraints(original_factory,session_factory):
    from journeyplus.agent.tools.contracts import WaitingInput
    from journeyplus.models import AgentWaitGoal
    from uuid import UUID
    identity=seed(original_factory)
    runtime,store,ctx=context(session_factory,original_factory)
    store.start(ctx.workspace_id,'创建本次测试等待任务','simple-wait',0)
    ctx.turn_id=store.load_context_index(ctx.workspace_id)['messages'][-1].metadata['turn_id']
    query={'sources':{'mode':'explicit','identities':[{'program_name':'Marriott Bonvoy','tier_name':'Platinum'}]}}
    direct=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':query})
    service=runtime.services['waiting']
    created=service.manage(WaitingInput(operation='create',query=query),ctx)
    assert created.error is None
    assert service.check()['status']=='RESULT_PENDING'
    listed=service.manage(WaitingInput(operation='list'),ctx)
    goal=listed.data['goals'][0]
    payload=store.artifacts.read(ctx.workspace_id,goal['result_snapshot_ref'])['payload']
    assert payload['matching_policy']=='simple-matching-v1'
    assert {(r['from'],r['to'],r['paid']) for r in payload['routes'].values()}=={(r['from'],r['to'],r['paid']) for r in direct.data['candidates']}
    assert set(payload['steps'])=={sid for r in payload['routes'].values() for sid in r['step_refs']}
    with session_factory.begin() as s:
        row=s.get(AgentWaitGoal,UUID(goal['ref'].removeprefix('goal:')))
        row.status='ACTIVE'
    with original_factory.begin() as s:
        row=s.get(ArticleOpportunityRecord,identity);facts=json.loads(json.dumps(row.facts))
        facts['application_routes'][0]['prices'][0]['amount']='99'
        row.facts=facts
    assert service.check()['status']=='DUPLICATE'
    with session_factory.begin() as s:
        row=s.get(AgentWaitGoal,UUID(goal['ref'].removeprefix('goal:')))
        row.query={**query,'constraints':{'max_amount':'100','currency':'USD'}}
        row.conditions_schema_version=3
    assert service.check()['status']=='NEEDS_RECONFIRMATION'
    with session_factory() as s:
        row=s.get(AgentWaitGoal,UUID(goal['ref'].removeprefix('goal:')))
        assert row.query['constraints']['max_amount']=='100'
