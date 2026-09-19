from datetime import datetime, UTC
from uuid import uuid4

from journeyplus.models import StatusEvent, FactSetRecord, BriefRecord, ArticleOpportunityRecord
from journeyplus.knowledge.workflow_knowledge import WorkflowActivityReader
from tests.test_agent_workflow_reads import original_factory, seed


def test_news_combines_sources_by_date_before_pagination(original_factory):
    article_id = seed(original_factory)
    with original_factory.begin() as session:
        article = session.get(ArticleOpportunityRecord, article_id)
        article.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        event = StatusEvent(created_from_key=str(uuid4()), program="Official", summary="News")
        session.add(event)
        session.flush()
        fact = FactSetRecord(event_id=event.id, version=1, schema_version="5", facts={})
        session.add(fact)
        session.flush()
        brief = BriefRecord(fact_set_id=fact.id, version=1, schema_version="1", content={},
                            updated_at=datetime(2026, 2, 1, tzinfo=UTC))
        session.add(brief)
        session.flush()
        event.current_fact_set_id, event.current_brief_id = fact.id, brief.id
        reader = WorkflowActivityReader(session)
        assert reader.locate(limit=1)[0].id == event.id
        assert reader.locate(limit=1, offset=1)[0].id == article_id
        article.created_at = datetime(2026, 3, 1, tzinfo=UTC)
        session.flush()
        assert reader.locate(limit=1)[0].id == article_id
        assert reader.locate(limit=1, offset=1)[0].id == event.id
