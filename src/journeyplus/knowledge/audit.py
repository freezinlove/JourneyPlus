"""Read-only statistics for the selected AIWorkflow business model."""
from sqlalchemy import func, inspect, select
from journeyplus.models import (
    Source, SourceItem, DocumentVersion, StatusEvent, FactSetRecord, BriefRecord,
    ArticleAnalysisRecord, ArticleOpportunityRecord, ArticleBriefRecord,
)


def workflow_audit(session):
    tables = set(inspect(session.connection()).get_table_names())
    models = (Source, SourceItem, DocumentVersion, StatusEvent, FactSetRecord,
              BriefRecord, ArticleAnalysisRecord, ArticleOpportunityRecord, ArticleBriefRecord)
    counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model))
              for model in models if model.__tablename__ in tables}
    activities = []
    for event in session.scalars(select(StatusEvent).order_by(StatusEvent.id)):
        facts = session.get(FactSetRecord, event.current_fact_set_id) if event.current_fact_set_id else None
        brief = session.get(BriefRecord, event.current_brief_id) if event.current_brief_id else None
        value = facts.facts if facts else {}
        routes = value.get('application_routes') or []
        activities.append({'event_id': str(event.id), 'program': event.program,
            'fact_version_id': str(event.current_fact_set_id) if event.current_fact_set_id else None,
            'fact_version': facts.version if facts else None,
            'brief_id': str(event.current_brief_id) if event.current_brief_id else None,
            'brief_matches_facts': bool(facts and brief and brief.fact_set_id == facts.id),
            'mapping_count': len(value.get('status_mappings') or []),
            'application_method_count': len(routes),
            'price_count': sum(len(r.get('prices') or []) for r in routes)})
    return {'data_model': 'aiworkflow', 'counts': counts, 'activities': activities}
