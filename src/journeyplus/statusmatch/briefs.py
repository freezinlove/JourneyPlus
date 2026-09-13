"""Publish official brief text from the already completed extraction, without AI."""
from sqlalchemy import select

from journeyplus.contracts import StatusMatchBrief
from journeyplus.knowledge.source_documents import source_links
from journeyplus.models import BriefRecord, StatusEvent


OFFICIAL_BRIEF_SCHEMA_VERSION = "statusmatch-brief-1"


def save_official_brief(session, fact_record, identity):
    event = session.get(StatusEvent, fact_record.event_id)
    if event is None or event.current_fact_set_id != fact_record.id:
        raise ValueError("FactSet changed before official brief publication")
    content = StatusMatchBrief(
        fact_set_id=fact_record.id, title=identity.title, summary=identity.summary,
        source_links=source_links(session, fact_record),
    ).model_dump(mode="json")
    records = list(session.scalars(select(BriefRecord).where(
        BriefRecord.fact_set_id == fact_record.id,
    ).order_by(BriefRecord.version.desc())))
    for existing in records:
        if existing.content == content:
            event.current_brief_id = existing.id
            return existing, True
    record = BriefRecord(
        fact_set_id=fact_record.id, version=(records[0].version if records else 0) + 1,
        schema_version=OFFICIAL_BRIEF_SCHEMA_VERSION, content=content,
    )
    session.add(record)
    session.flush()
    event.current_brief_id = record.id
    return record, False
