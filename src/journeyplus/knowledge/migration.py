"""Auditable additive migration. Unproven associations are never guessed."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from journeyplus.models import (ArticleOpportunityRecord, DocumentVersion, FactSetRecord,
                                SourceItem, StatusEvent, StatusHolding)
from journeyplus.knowledge.models import Activity, KnowledgeMigrationLink, MembershipTier
from journeyplus.knowledge.publication import CatalogService, canonical_key, signature
from journeyplus.knowledge.sources import section_document

MIGRATION_VERSION="activity-knowledge-1"
LEGACY_ROLES={
    "status_events":"activity identity",
    "fact_sets":"versioned facts; mapping/price association requires source evidence",
    "article_opportunities":"source-neutral activity identity and scoped facts",
    "document_versions":"reused immutable source versions plus semantic sections",
    "event_evidence":"exact section evidence or unresolved document-level locator",
    "event_revisions":"knowledge/source history",
    "briefs":"read-only legacy derived text",
    "article_briefs":"read-only legacy derived text",
    "status_holdings":"preserve ID; normalize program/tier",
    "agent_interactions":"expire legacy interaction; new versioned workspace",
    "agent_wait_goals":"preserve explicit task and confirmed conditions",
}


def migration_audit(session:Session) -> dict:
    """No chat, holdings content, source body or credentials in diagnostic output."""
    from sqlalchemy import inspect, text
    tables=set(inspect(session.connection()).get_table_names())
    counts={table:session.scalar(text(f'SELECT count(*) FROM "{table}"')) for table in LEGACY_ROLES if table in tables}
    rows=[]
    for event in session.scalars(select(StatusEvent).order_by(StatusEvent.created_at,StatusEvent.id)):
        facts=session.get(FactSetRecord,event.current_fact_set_id) if event.current_fact_set_id else None
        value=facts.facts if facts else {}
        routes=value.get("application_routes") or []
        rows.append({"legacy_id":str(event.id),"program":event.program,"fact_version_id":str(facts.id) if facts else None,
                     "mapping_count":len(value.get("status_mappings") or []),"application_method_count":len(routes),
                     "price_count":sum(len(r.get("prices") or []) for r in routes),"signature":signature(value),
                     "association_status":"REQUIRES_EVIDENCE_RECONCILIATION" if routes else "NO_STRUCTURED_METHOD"})
    return {"migration_version":MIGRATION_VERSION,"counts":counts,"table_roles":LEGACY_ROLES,
            "activities":rows,"facts_signature":signature(rows)}


def _link(s:Session,table:str,identifier:UUID,path:str,target_table:str,target_id:UUID|None,status:str,reason:str):
    row=s.scalar(select(KnowledgeMigrationLink).where(KnowledgeMigrationLink.legacy_table==table,
        KnowledgeMigrationLink.legacy_id==str(identifier),KnowledgeMigrationLink.legacy_path==path,
        KnowledgeMigrationLink.migration_version==MIGRATION_VERSION))
    if row is None:
        row=KnowledgeMigrationLink(legacy_table=table,legacy_id=str(identifier),legacy_path=path,target_table=target_table,
            target_id=target_id,status=status,reason=reason,migration_version=MIGRATION_VERSION)
        s.add(row);s.flush()
    return row


def backfill_identity_and_sources(s:Session) -> dict:
    c=CatalogService(s)
    activities=[]
    for cls,table in [(StatusEvent,"status_events"),(ArticleOpportunityRecord,"article_opportunities")]:
        for old in s.scalars(select(cls)):
            program=c.program(old.program)
            identity=f"legacy:{table}:{old.id}"
            activity=s.scalar(select(Activity).where(Activity.identity_key==identity))
            value=old.facts if table=="article_opportunities" else ((f.facts if (f:=s.get(FactSetRecord,old.current_fact_set_id)) else {}) if old.current_fact_set_id else {})
            if activity is None:
                activity=Activity(identity_key=identity,primary_program_id=program.id,kind=value.get("opportunity_kind","OTHER"),
                                  edition_key=f"legacy:{old.id}")
                s.add(activity);s.flush()
            _link(s,table,old.id,"", "activities",activity.id,"MAPPED","Preserved source identity; no cross-edition brand merge")
            for index,mapping in enumerate(value.get("status_mappings") or []):
                source=c.program(mapping["source_program"])
                for tier in mapping.get("source_tiers") or []: c.tier(source.id,tier)
                if mapping.get("target_tier"): c.tier(program.id,mapping["target_tier"])
                _link(s,table,old.id,f"status_mappings/{index}","option_mappings",None,"UNRESOLVED",
                      "Source mapping has no explicit application option identity; re-extract scoped evidence")
            for route_index,route in enumerate(value.get("application_routes") or []):
                for price_index,price in enumerate(route.get("prices") or []):
                    reason="Numeric value retained in legacy source; option/source/target applicability must be evidenced"
                    if price.get("amount") in (0,"0","0.0"):
                        reason="Legacy zero is not proof of free; require explicit free evidence"
                    _link(s,table,old.id,f"application_routes/{route_index}/prices/{price_index}","option_prices",None,"UNRESOLVED",reason)
            activities.append(str(activity.id))
    for doc in s.scalars(select(DocumentVersion)):
        section_document(s,doc.id)
        _link(s,"document_versions",doc.id,"","document_versions",doc.id,"MAPPED","Reused allowed normalized body; stable section parser")
    for holding in s.scalars(select(StatusHolding)):
        p=c.program(holding.program_display_name);t=c.tier(p.id,holding.tier_display_name)
        # Preserve explicit user labels; alias matching never selects an ambiguous foreign tier.
        holding.program_id=p.id;holding.tier_id=t.id;holding.identity_status="CONFIRMED"
        _link(s,"status_holdings",holding.id,"","status_holdings",holding.id,"MAPPED","Confirmed user identity preserved without changing labels or expiry")
    s.flush()
    return {"activity_count":len(activities),"links":dict(s.execute(select(KnowledgeMigrationLink.status,func.count()).group_by(KnowledgeMigrationLink.status)).all()),
            "published_count":sum(s.get(Activity,UUID(x)).current_version_id is not None for x in activities)}
