"""Detect reasons to review an edition; never infer that a new edition is valid."""
import re

from sqlalchemy import select

from journeyplus.knowledge.models import ActivityDocument,ActivityKnowledgeVersion,DocumentSection,ActivityEditionReview
from journeyplus.knowledge.sources import create_evidence


MARKER=re.compile(r'new (?:round|campaign)|(?:eligibility|application) reset|(?:apply|eligible) again|applications? reopen|campaign (?:id|identifier)|新一轮|资格重置|可再次申请|活动标识',re.I)


def edition_signals(session,activity,bindings,source_identity):
    if not activity.current_version_id or not source_identity:return []
    review=session.scalar(select(ActivityEditionReview).where(
        ActivityEditionReview.source_table==source_identity[0],ActivityEditionReview.source_id==source_identity[1]).order_by(ActivityEditionReview.created_at.desc(),ActivityEditionReview.id.desc()).limit(1))
    if review and review.decision!='UNRESOLVED':
        approved=review.request_json
        if set(approved.get('reviewed_document_ids',approved['official_document_ids']))=={str(b.document_version_id) for b in bindings}:
            return []
    previous=session.get(ActivityKnowledgeVersion,activity.current_version_id)
    prior=list(session.scalars(select(ActivityDocument).where(ActivityDocument.knowledge_version_id==previous.id)))
    def sections(docid,scope):
        return [s for s in session.scalars(select(DocumentSection).where(DocumentSection.document_version_id==docid,DocumentSection.kind!='ROW'))
                if not scope or str(s.id) in set(map(str,scope))]
    old_lines={line.strip() for b in prior for section in sections(b.document_version_id,b.section_scope) for line in section.body.splitlines() if MARKER.search(line)}
    signals=[]
    for binding in bindings:
        for section in sections(binding.document_version_id,binding.section_ids):
            if any(MARKER.search(line) and line.strip() not in old_lines for line in section.body.splitlines()):
                signals.append(create_evidence(session,section.id,section.body).id)
    return signals
