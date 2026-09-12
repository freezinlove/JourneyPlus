"""Exercise the production assembly on original business tables plus runtime migration."""
import asyncio
from dataclasses import replace
import importlib.util
from pathlib import Path
from time import monotonic
from uuid import uuid4, UUID
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select, text
from fastapi.testclient import TestClient
from tests.test_agent_workflow_reads import original_factory, seed, call
from tests.test_harness_runtime import FakeModel
from journeyplus.agent.composition import compose_business
from journeyplus.agent.harness.contracts import ExecutionContext
from journeyplus.agent.tools.contracts import HoldingsWriteInput, HoldingsReadInput, WaitingInput
from journeyplus.agent.adapters.workflow_holdings import WorkflowHolding, holding_revision
from journeyplus.agent.adapters.storage_readiness import storage_status
from journeyplus.product.agent_api import create_agent_app


@pytest.fixture
def migrated(original_factory):
    path=Path(__file__).parents[1]/'migrations/versions/0019_original_agent_runtime.py'
    spec=importlib.util.spec_from_file_location('original_runtime_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with original_factory.kw['bind'].begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
    return original_factory


def setup(factory, prompt='请保存我的测试俱乐部金卡，之后允许更新或删除这条测试记录，并创建、更新和取消测试等待任务。'):
    runtime,store=compose_business(factory,FakeModel([]))
    workspace=store.create();store.start(workspace['id'],prompt,'test-user-message',0)
    message=store.load_context_index(workspace['id'])['messages'][0]
    ctx=ExecutionContext(workspace['id'],message.metadata['turn_id'],str(uuid4()),'local-user',
        monotonic()+60,asyncio.Event(),store.artifacts,store,runtime.services)
    auth={'message_refs':[message.id],'quotes':[prompt]}
    return runtime,store,ctx,auth


def test_migration_preserves_business_model_and_readiness(migrated):
    inspector=inspect(migrated.kw['bind'])
    assert len(inspector.get_table_names())==38  # baseline fixture has no alembic_version
    assert not set(inspector.get_table_names()) & {'membership_programs','membership_tiers','activities','user_business_operations'}
    assert {c['name'] for c in inspector.get_columns('status_holdings')}=={
        'id','program_key','tier_key','program_display_name','tier_display_name','valid_until','created_at','updated_at'}
    assert storage_status(migrated)['status']=='AVAILABLE'
    runtime,store,ctx,_=setup(migrated)
    assert runtime.services['maintenance']()=={'cleanup':0,'waiting':{'status':'NO_ACTIVE_GOAL','model_calls':0}}


def test_missing_runtime_returns_specific_failure_before_model(original_factory):
    class Model(FakeModel):
        initialized=False
        async def initialize(self): self.initialized=True
    model=Model([])
    runtime,store=compose_business(original_factory,model)
    with TestClient(create_agent_app(runtime,store)) as client:
        response=client.post('/v3/agent/workspaces',json={})
        assert response.status_code==503
        assert response.json()['code']=='AGENT_STORAGE_SCHEMA_MISMATCH'
        state=client.get('/v3/agent/status').json()
        assert state['status']=='UNAVAILABLE' and not state['ready_for_route_queries']
        assert not model.initialized


def test_original_memory_authorization_idempotency_update_delete(migrated):
    runtime,store,ctx,auth=setup(migrated)
    memory=runtime.services['user_memory']
    args=HoldingsWriteInput(operation='create',identity={'program_name':'测试俱乐部','tier_name':'金卡'})
    first=memory.write(args,ctx)
    assert not first.error,first
    assert first.data==memory.write(args,ctx).data
    holding=first.data['after']
    assert holding['identity_status']=='NEEDS_CONFIRMATION'
    read=memory.read(HoldingsReadInput())[0]
    assert read['source_record']['original_statements'][0]['text']==auth['quotes'][0]
    with migrated.begin() as s:
        row=s.get(WorkflowHolding,UUID(holding['ref'][8:]));row.valid_until=__import__('datetime').date(2028,1,1)
    stale=HoldingsWriteInput(operation='delete',holding_ref=holding['ref'],expected_revision=holding['revision'])
    assert memory.write(stale,replace(ctx,call_id="stale")).error.code=='CONFLICT'
    current=memory.read(HoldingsReadInput())[0]
    assert current['source_record']=={}  # an external edit cannot inherit an old verified receipt
    update=HoldingsWriteInput(operation='update',holding_ref=current['ref'],expected_revision=current['revision'],valid_until=None)
    result=memory.write(update,replace(ctx,call_id="update"));assert not result.error,result
    delete=stale.model_copy(update={'expected_revision':result.data['after']['revision']})
    assert not memory.write(delete,replace(ctx,call_id="delete")).error
    assert memory.read(HoldingsReadInput())==[]
    assert memory.write(args,replace(ctx,turn_id=str(uuid4()),call_id='missing-turn')).error.code=='NOT_AUTHORIZED'


def test_known_holding_saved_routes_waiting_and_lifecycle(migrated):
    seed(migrated)
    runtime,store,ctx,auth=setup(migrated)
    result=runtime.services['user_memory'].write(HoldingsWriteInput(operation='create',
        identity={'program_name':'Marriott Bonvoy','tier_name':'Platinum'}),ctx)
    assert not result.error,result
    assert result.data['after']['tier_ref']
    routes=call(runtime,ctx,'routes.evaluate',{'operation':'search','query':{'sources':{'mode':'saved'}}})
    assert routes.data['candidates']
    waiting=runtime.services['waiting']
    args=WaitingInput(operation='create',query={'sources':{'mode':'saved'}})
    created=waiting.manage(args,replace(ctx,call_id="wait-create"));assert not created.error,created
    goal=created.data['after']
    assert waiting.check()['status'] in {'NO_HIT','RESULT_PENDING'}
    listed=waiting.manage(WaitingInput(operation='list'),ctx)
    current=listed.data['goals'][0]
    update=WaitingInput(operation='update',goal_ref=current['ref'],expected_revision=current['revision'],
        query={'sources':{'mode':'saved'},'constraints':{'free_only':True}})
    updated=waiting.manage(update,replace(ctx,call_id="wait-update"));assert not updated.error,updated
    canceled=waiting.manage(WaitingInput(operation='cancel',goal_ref=goal['ref'],expected_revision=updated.data['after']['revision']),replace(ctx,call_id='wait-cancel'))
    assert not canceled.error,canceled
    assert waiting.check()['status']=='NO_ACTIVE_GOAL'


def test_original_product_holding_form_and_activity_details(migrated):
    identity=seed(migrated)
    from journeyplus.product.api import create_product_app
    app=create_product_app(migrated)
    with TestClient(app) as client:
        cards=client.get('/v2/activities?view=cards').json()
        assert cards['activities'] and not cards['has_more']
        version=cards['activities'][0]['version_ref']
        detail=client.get(f'/v2/activities/{identity}?version_ref={version}')
        assert detail.status_code==200,detail.text
        assert detail.json()['data_model']=='aiworkflow'
        assert detail.json()['options'][-1]['mappings'][0]['from_program']=='Marriott Bonvoy'
        body={'program_key':'marriott bonvoy','tier_key':'platinum','valid_until':'2028-01-01'}
        created=client.post('/v1/status-holdings',json=body)
        assert created.status_code==201,created.text
        holding=created.json()
        updated=client.patch('/v1/status-holdings/'+holding['id'],json={**body,'valid_until':None})
        assert updated.status_code==200,updated.text
        assert updated.json()['valid_until'] is None
        assert client.delete('/v1/status-holdings/'+holding['id']).status_code==204
        assert client.get('/v1/status-holdings').json()==[]


def test_production_autogenerate_cannot_restore_retired_catalog(migrated):
    from journeyplus.agent.adapters.schema import production_metadata
    metadata=production_metadata()
    assert set(metadata.tables)==set(inspect(migrated.kw['bind']).get_table_names())
    assert len(metadata.sorted_tables)==38
    assert 'program_id' not in metadata.tables['status_holdings'].c
    assert metadata.tables['source_items'].c.document_role.nullable
