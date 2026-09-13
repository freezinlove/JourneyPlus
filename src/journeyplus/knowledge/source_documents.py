"""Document directories from existing production associations; never load bodies."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import load_only

from journeyplus.models import (
    ArticleAnalysisRecord, DocumentVersion, StatusMatchChangeSet,
)


def source_documents(session, record):
    """Resolve the input snapshot for a FactSet or article opportunity.

    Reused facts may have later unchanged snapshots. Prefer their first recorded
    input batch, not a watch's mutable current page. Historical evidence is only
    a fallback for records predating document-level associations.
    """
    ids = []
    if getattr(record, 'analysis_id', None):
        analysis = session.get(ArticleAnalysisRecord, record.analysis_id)
        if analysis:
            ids = [analysis.document_version_id]
    else:
        batch = session.scalar(select(StatusMatchChangeSet).where(
            StatusMatchChangeSet.to_fact_set_id == record.id,
            StatusMatchChangeSet.event_id == record.event_id,
        ).order_by(StatusMatchChangeSet.created_at, StatusMatchChangeSet.id).limit(1))
        if batch:
            ids = [batch.activity_document_version_id, batch.faq_document_version_id,
                   batch.terms_document_version_id]
    if not any(ids):
        def visit(value):
            if isinstance(value, dict):
                if value.get('document_version_id'):
                    try:
                        ids.append(UUID(str(value['document_version_id'])))
                    except ValueError:
                        pass
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(record.facts)
    return list(session.scalars(select(DocumentVersion).options(load_only(
        DocumentVersion.id, DocumentVersion.canonical_url, DocumentVersion.fetched_at,
    )).where(DocumentVersion.id.in_([identity for identity in ids if identity]))
        .order_by(DocumentVersion.id)))


def source_links(session, record):
    return sorted({document.canonical_url for document in source_documents(session, record)})
