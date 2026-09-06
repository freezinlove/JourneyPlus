from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID, uuid5
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.models import DocumentVersion
from journeyplus.knowledge.models import DocumentSection, EvidenceReference

SECTION_PARSER_VERSION = "semantic-sections-1"
TOPICS = {
    "PRICE": r"fee|price|cost|eur|usd|费用|收费|免费|价格",
    "ELIGIBILITY": r"eligible|eligibility|qualif|obtained|membership|tier|match|资格|会籍|等级|匹配|条件",
    "CHALLENGE": r"challenge|nights?|stays?|挑战|住宿",
    "WINDOW": r"deadline|until|valid|截止|有效|期限",
    "VALIDITY": r"validity|valid for|duration|\b[0-9]+\s*months?\b|有效期|有效.*月",
    "APPLICATION": r"apply|application|申请|submit|提交",
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def require_knowledge_content(doc: DocumentVersion) -> None:
    """Check at every read boundary, including already materialized evidence."""
    if doc.storage_mode == 'restricted_mail_snapshot':
        raise ValueError('Mail discovery content is not activity knowledge; use its official linked pages')
    host = (urlsplit(doc.canonical_url).hostname or '').casefold()
    if host=='statusmatcher.com' or host.endswith('.statusmatcher.com'):
        raise ValueError('StatusMatcher experience belongs only to the temporary workspace, not published activity knowledge')
    if host.endswith('.statusmatch.com') and re.search(
            r'(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?StatusMatch\.Com\s+Terms\s+of\s+Use\b',
            doc.normalized_body):
        raise ValueError('Unscoped public Terms content must be recollected before knowledge use')


def section_document(session: Session, document_id: UUID) -> list[DocumentSection]:
    """Segment allowed normalized text; never fetch or reintroduce excluded HTML."""
    doc = session.get(DocumentVersion, document_id)
    if doc is None:
        raise LookupError("Document version does not exist")
    require_knowledge_content(doc)
    existing = list(session.scalars(select(DocumentSection).where(
        DocumentSection.document_version_id == document_id).order_by(DocumentSection.ordinal)))
    if existing:
        return existing
    text = doc.normalized_body
    lines = text.splitlines(keepends=True)
    chunks: list[dict] = []
    heading: list[str] = []
    parent: UUID | None = None
    offset = 0
    pending: list[str] = []
    start = 0

    def flush():
        nonlocal pending
        body = "".join(pending).rstrip()
        if body.strip():
            ordinal = len(chunks)
            kind = "TABLE" if sum("|" in l for l in pending) >= 2 else "FAQ" if re.match(r"(?i)\s*(?:Q[:：.]|question|问[:：])", body) else "PARAGRAPH"
            sid = uuid5(document_id, f"{SECTION_PARSER_VERSION}:{ordinal}:{digest(body)}")
            chunks.append(dict(id=sid, kind=kind, body=body, ordinal=ordinal,
                               heading_path=heading.copy(), parent_id=parent,
                               locator={"start":start,"end":start+len(body),"parser_version":SECTION_PARSER_VERSION}))
        pending = []

    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            flush()
            heading = heading[:len(match[1])-1] + [match[2]]
            sid = uuid5(document_id, f"{SECTION_PARSER_VERSION}:heading:{offset}")
            chunks.append(dict(id=sid,kind="HEADING",body=line.rstrip(),ordinal=len(chunks),
                               heading_path=heading.copy(),parent_id=None,
                               locator={"start":offset,"end":offset+len(line.rstrip()),"parser_version":SECTION_PARSER_VERSION}))
            parent = sid
        elif not line.strip():
            flush()
        else:
            if not pending:
                start = offset
            pending.append(line)
        offset += len(line)
    flush()
    # Rows retain their containing table. The table itself retains neighbouring
    # footnotes, so drilling into a row never discards headers or qualifications.
    expanded_chunks=[]
    for c in chunks:
        c["ordinal"]=len(expanded_chunks);expanded_chunks.append(c)
        if c["kind"]=="TABLE":
            row_offset=c["locator"]["start"]
            for row in c["body"].splitlines(keepends=True):
                if "|" in row and not re.fullmatch(r"[\s|:\-]+",row):
                    sid=uuid5(document_id,f"{SECTION_PARSER_VERSION}:row:{row_offset}:{digest(row)}")
                    expanded_chunks.append(dict(id=sid,kind="ROW",body=row.rstrip(),ordinal=len(expanded_chunks),
                        heading_path=c["heading_path"],parent_id=c["id"],
                        locator={"start":row_offset,"end":row_offset+len(row.rstrip()),"parser_version":SECTION_PARSER_VERSION}))
                row_offset+=len(row)
        elif re.match(r"\s*(?:\[\^.+?\]:|\*\s|Note\b|注[:：]|备注)",c["body"],re.I):
            c["kind"]="FOOTNOTE"
    chunks=expanded_chunks
    # Keep the complete table and neighbouring caveats together. Each snippet expansion
    # includes the heading's entire local group, not an isolated price/negative sentence.
    records = []
    for c in chunks:
        related = [str(x["id"]) for x in chunks if x["id"] != c["id"] and
                   (x["parent_id"] == c["parent_id"] or x["id"] == c["parent_id"])]
        rec = DocumentSection(document_version_id=document_id,section_key=str(c["id"]),
                              related_section_ids=related,
                              topics=[k for k,p in TOPICS.items() if re.search(p,c["body"],re.I)],**c)
        records.append(rec)
    # Parent headings must exist before child rows with composite foreign keys.
    for rec in records:
        session.add(rec)
        session.flush()
    doc.section_parser_version = SECTION_PARSER_VERSION
    session.flush()
    return records


def create_evidence(session: Session, section_id: UUID, quote: str) -> EvidenceReference:
    section = session.get(DocumentSection, section_id)
    if section is None or not quote.strip() or quote not in section.body:
        raise ValueError("Evidence must quote text from the exact source section")
    require_knowledge_content(session.get(DocumentVersion, section.document_version_id))
    key = digest(json.dumps([str(section_id), quote], ensure_ascii=False))
    old = session.scalar(select(EvidenceReference).where(
        EvidenceReference.document_version_id == section.document_version_id,
        EvidenceReference.content_hash == key))
    if old:
        return old
    ref = EvidenceReference(document_version_id=section.document_version_id,section_id=section_id,
                            precision="SECTION",locator={**section.locator,"quote_offset":section.body.index(quote)},
                            quote=quote,content_hash=key)
    session.add(ref)
    session.flush()
    return ref


def related_section_scope(section, sections):
    """A markdown FAQ question and its full answer form one disclosure unit.

    Old snapshots grouped every unheaded paragraph together. Recompute this read
    boundary without mutating immutable source sections or their evidence IDs.
    """
    def question(row):
        return bool(re.match(r'\s*\*\s+\*\*.+[?？]\*\*\s*$',row.body,re.S))
    index=next(i for i,row in enumerate(sections) if row.id==section.id)
    start=None
    for i in range(index,-1,-1):
        if sections[i].kind in {'HEADING','TABLE','ROW'}:break
        if question(sections[i]):start=i;break
    if start is not None:
        end=start+1
        while end<len(sections) and not question(sections[end]) and sections[end].kind not in {'HEADING','TABLE','ROW'}:
            end+=1
        return {row.id for row in sections[start:end]}
    return {section.id,*(UUID(x) for x in section.related_section_ids)}


def expand_evidence(session: Session, evidence_id: UUID, *, allowed_sections: set[UUID] | None = None) -> dict:
    evidence = session.get(EvidenceReference, evidence_id)
    if evidence is None:
        raise LookupError("Unknown evidence reference")
    doc = session.get(DocumentVersion, evidence.document_version_id)
    require_knowledge_content(doc)
    section = session.get(DocumentSection, evidence.section_id) if evidence.section_id else None
    if section and allowed_sections is not None and section.id not in allowed_sections:
        raise ValueError("Evidence outside activity section scope")
    sections = []
    if section:
        siblings=list(session.scalars(select(DocumentSection).where(DocumentSection.document_version_id==doc.id).order_by(DocumentSection.ordinal)))
        ids = related_section_scope(section,siblings)
        if section.kind=="ROW" and section.parent_id:
            table=session.get(DocumentSection,section.parent_id)
            ids.update(UUID(x) for x in table.related_section_ids)
        if allowed_sections is not None:
            ids &= allowed_sections
        sections = list(session.scalars(select(DocumentSection).where(DocumentSection.id.in_(ids)).order_by(DocumentSection.ordinal)))
    return {"ref":str(evidence.id),"precision":evidence.precision,"document_version_id":str(doc.id),
            "url":doc.canonical_url,"fetched_at":doc.fetched_at.isoformat(),"quote":evidence.quote,
            "sections":[{"ref":str(s.id),"heading":s.heading_path,"text":s.body} for s in sections]}
