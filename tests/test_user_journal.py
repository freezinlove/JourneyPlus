from copy import deepcopy
from datetime import UTC,datetime
import pytest
from sqlalchemy import select,create_engine
from sqlalchemy.orm import sessionmaker
from journeyplus.models import Base,StatusHolding,AgentWaitGoal,UserBusinessOperation
from journeyplus.knowledge.user_journal import enable_journal,export_operations,replay_operations,snapshot
from tests.test_workspace import factory


def holding():
    return StatusHolding(program_key='example',tier_key='gold',program_display_name='Example',tier_display_name='Gold')


def test_opt_in_and_transaction_atomicity(factory):
    with factory.begin() as s:s.add(holding())
    with factory() as s:assert export_operations(s)==[]
    enable_journal(factory)
    with pytest.raises(RuntimeError),factory.begin() as s:
        row=s.scalar(select(StatusHolding));row.tier_key='silver';s.flush()
        assert len(export_operations(s))==1
        raise RuntimeError('rollback')
    with factory() as s:
        assert export_operations(s)==[]
        assert s.scalar(select(StatusHolding)).tier_key=='gold'


def test_create_update_delete_wait_and_idempotent_replay(factory):
    enable_journal(factory)
    with factory.begin() as s:
        row=holding();goal=AgentWaitGoal(status='ACTIVE',query={},conditions_schema_version=2)
        s.add_all([row,goal]);s.flush();hid=row.id;gid=goal.id
    with factory.begin() as s:
        s.get(StatusHolding,hid).tier_key='platinum'
        s.get(AgentWaitGoal,gid).status='COMPLETED'
        s.get(AgentWaitGoal,gid).ended_at=datetime(2026,9,6,tzinfo=UTC)
    with factory.begin() as s:s.delete(s.get(StatusHolding,hid))
    with factory() as s:
        operations=export_operations(s);assert len(operations)==5
        expected=snapshot(AgentWaitGoal,s.get(AgentWaitGoal,gid))
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);clone=sessionmaker(engine)
    with clone.begin() as s:assert replay_operations(s,operations)=={'applied':5,'duplicates':0}
    with clone.begin() as s:
        assert replay_operations(s,operations)=={'applied':0,'duplicates':5}
        assert s.get(StatusHolding,hid) is None
        assert snapshot(AgentWaitGoal,s.get(AgentWaitGoal,gid))==expected
    engine.dispose()


def test_divergent_state_and_tamper_rejected(factory):
    enable_journal(factory)
    with factory.begin() as s:s.add(holding())
    with factory() as s:operations=export_operations(s)
    bad=deepcopy(operations);bad[0]['after_state']['tier_key']='forged'
    with pytest.raises(ValueError,match='checksum'),factory.begin() as s:replay_operations(s,bad)
    with factory.begin() as s:
        row=s.scalar(select(StatusHolding));row.tier_key='newer'
        for journal in s.scalars(select(UserBusinessOperation)):s.delete(journal)
    with pytest.raises(ValueError,match='diverged'),factory.begin() as s:replay_operations(s,operations)
    with factory() as s:assert s.scalar(select(StatusHolding)).tier_key=='newer'


def test_maintenance_fences_background_orm_writes(factory):
    from journeyplus.knowledge.user_journal import configure_user_data
    with factory.begin() as s:s.add(AgentWaitGoal(status='ACTIVE',query={}))
    configure_user_data(factory,'rollback')
    with pytest.raises(ValueError,match='USER_WRITES_PAUSED'),factory.begin() as s:
        s.scalar(select(AgentWaitGoal)).status='COMPLETED'
    with factory() as s:assert s.scalar(select(AgentWaitGoal)).status=='ACTIVE'
