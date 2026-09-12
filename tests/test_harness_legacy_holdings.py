"""Legacy product writes and Agent writes share identity, revision and journal."""
from types import SimpleNamespace
from uuid import UUID
from dataclasses import replace
from sqlalchemy import select
from journeyplus.product.holdings import StatusHoldingService
from journeyplus.product.contracts import StatusHoldingInput
from journeyplus.models import StatusHolding
from journeyplus.agent.tools.contracts import HoldingsWriteInput
from tests.test_harness_tools import context


def test_legacy_edit_then_agent_update_preserves_one_membership(session_factory,monkeypatch):
    monkeypatch.setattr(StatusHoldingService,'_catalog_node',lambda self,program,tier:
        SimpleNamespace(program_key=program,tier_key=tier,program='Example-Air',tier=tier.title()))
    with session_factory.begin() as session:
        legacy=StatusHoldingService(session)
        saved=legacy.upsert(StatusHoldingInput(program_key='example air',tier_key='silver'))
        row=session.get(StatusHolding,saved.id);identity=row.id;silver=row.tier_id
        assert row.revision==1 and silver
        legacy.update(row.id,StatusHoldingInput(program_key='example air',tier_key='gold'))
        assert row.revision==2 and row.tier_id!=silver
        legacy.upsert(StatusHoldingInput(program_key='example air',tier_key='gold'))
        assert row.revision==2
    runtime,store,w,ctx=context(session_factory)
    store.start(w['id'],'请把我的 Example-Air 改成 Silver','one',0)
    message=store.load_context_index(w['id'])['messages'][0]
    ctx=replace(ctx,turn_id=message.metadata['turn_id'])
    args=HoldingsWriteInput(operation='update',holding_ref='holding:'+str(identity),expected_revision=2,
        identity={'ref':'tier:'+str(silver)})
    result=runtime.services['user_memory'].write(args,ctx)
    assert result.data['outcome']=='APPLIED'
    with session_factory() as session:
        rows=list(session.scalars(select(StatusHolding)))
        assert len(rows)==1 and rows[0].id==identity and rows[0].tier_id==silver
        assert rows[0].revision==3 and rows[0].program_key=='example air'
