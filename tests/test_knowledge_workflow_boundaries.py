"""Preserved behavior from the retired workspace suite; local fake provider only."""
import pytest
from journeyplus.ai.provider import SequenceAIProvider

def test_workflow_model_runs_outside_database_transaction(session_factory):
    from tests.test_knowledge import fixture_draft
    from journeyplus.knowledge.workflow import KnowledgeWorkflow
    from journeyplus.knowledge.contracts import KnowledgeDraft
    from journeyplus.knowledge.models import Activity
    from sqlalchemy import event
    with session_factory.begin() as s:
        draft, _, _ = fixture_draft(s)
    workflow = KnowledgeWorkflow(session_factory, None)
    prepared = workflow.prepare(draft.activity_id, draft.documents)
    data = draft.model_dump(mode='json')
    data['extraction_key'] = prepared.extraction_key
    class Provider:
        def generate_structured(self, **kwargs):
            assert engine.pool.checkedout() == 0 if hasattr(engine.pool, 'checkedout') else not active
            return kwargs["output_model"].model_validate({"facts":data["facts"],"options":data["options"]})
    engine = session_factory.kw['bind']
    active = set()
    event.listen(engine, 'begin', lambda conn: active.add(id(conn)))
    event.listen(engine, 'commit', lambda conn: active.discard(id(conn)))
    event.listen(engine, 'rollback', lambda conn: active.discard(id(conn)))
    workflow.provider = Provider()
    result = workflow.publish(workflow.extract(prepared))
    assert result['status'] == 'PUBLISHED'
    with session_factory() as s:
        assert str(s.get(Activity, draft.activity_id).current_version_id) == result['version_id']

def test_workflow_rejects_model_changed_source_binding(session_factory):
    from tests.test_knowledge import fixture_draft
    from journeyplus.knowledge.workflow import KnowledgeWorkflow
    with session_factory.begin() as s:
        draft, _, _ = fixture_draft(s)
    provider = SequenceAIProvider([draft.model_dump(mode='json'),draft.model_dump(mode='json')])
    workflow = KnowledgeWorkflow(session_factory, provider)
    prepared = workflow.prepare(draft.activity_id, draft.documents)
    with pytest.raises(ValueError, match='Extra inputs'):
        workflow.extract(prepared)
