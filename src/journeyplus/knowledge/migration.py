"""Auditable additive migration. Unproven associations are never guessed."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from journeyplus.models import (ArticleAnalysisRecord, ArticleOpportunityRecord, DocumentVersion, FactSetRecord,
                                SourceItem, StatusEvent, StatusHolding)
from journeyplus.knowledge.models import Activity, KnowledgeMigrationLink, MembershipTier
from journeyplus.knowledge.publication import CatalogService, canonical_key, signature
from journeyplus.knowledge.sources import section_document

from journeyplus.knowledge.ingestion_scope import article_scope_reason

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


def migration_manifest(session:Session)->dict:
    """Read-only coverage of every table plus exact old-entry replacements."""
    from sqlalchemy import inspect,text
    from journeyplus.knowledge.compatibility import legacy_opportunity
    groups={
        'REUSE_SOURCE':{'sources','source_items','document_versions'},
        'REEXTRACT_WITH_EVIDENCE':{'status_events','fact_sets','event_evidence','event_revisions'},
        'NEW_ARTICLES_ONLY':{'article_opportunities','article_analyses'},
        'RETAIN_PROCESS_AUDIT':{'statusmatch_watches','statusmatch_watch_pages','statusmatch_change_sets','statusmatch_article_routes','statusmatch_article_supplements'},
        'RETAIN_READ_ONLY_HISTORY':{'briefs','article_briefs'},
        'PRESERVE_USER_BUSINESS':{'status_holdings','agent_wait_goals','user_business_operations'},
        'EXPIRING_WORKSPACE':{'agent_interactions','agent_turns','agent_workspace_messages'},
        'UNIFIED_KNOWLEDGE':{'activities','membership_programs','knowledge_migration_links','membership_tiers','activity_knowledge_versions',
            'activity_observation_state','application_options','membership_aliases','activity_briefs','activity_documents','application_option_versions',
            'document_sections','evidence_references','option_mappings','option_price_mappings','option_prices','activity_edition_reviews'},
        'RETAIN_UNRELATED_OPERATIONS':{'analysis_runs','alembic_version','automation_leases','automation_runs','buy_points_snapshots',
            'collection_runs','buy_points_offers','gold_cases','initialization_runs','job_runs','review_decisions','source_automation_states'},
    }
    roles={table:role for role,tables in groups.items() for table in tables}
    tables=[]
    for table in sorted(inspect(session.connection()).get_table_names()):
        quoted=session.bind.dialect.identifier_preparer.quote(table)
        tables.append({'table':table,'rows':session.scalar(text(f'SELECT count(*) FROM {quoted}')),
                       'disposition':roles.get(table,'UNCLASSIFIED_RETAIN')})
    replacements=[legacy_opportunity(session,identity) for model in (StatusEvent,FactSetRecord,ArticleOpportunityRecord)
                  for identity in session.scalars(select(model.id).order_by(model.id))]
    from collections import Counter
    link_counts=Counter((row.legacy_table,row.target_table,row.status) for row in session.scalars(select(KnowledgeMigrationLink)))
    return {'migration_version':MIGRATION_VERSION,'tables':tables,'unclassified_tables':[v['table'] for v in tables if v['disposition']=='UNCLASSIFIED_RETAIN'],
            'old_entry_replacements':replacements,'replacement_counts':dict(Counter(v['status'] for v in replacements)),
            'link_counts':[{'from':a,'to':b,'status':c,'count':n} for (a,b,c),n in sorted(link_counts.items())],
            'rules':['Old fact sets are not copied into published versions without evidence reconciliation.',
                     'UNRESOLVED mappings/prices remain audit gaps; an identity link alone is not a published replacement.',
                     'Excluded old articles remain archived even when isolated validation has a published copy.',
                     'No table is dropped by this inventory; unknown tables require review.']}


def _link(s:Session,table:str,identifier:UUID,path:str,target_table:str,target_id:UUID|None,status:str,reason:str):
    from journeyplus.models import Base
    allowed={'activities','activity_knowledge_versions','document_versions','evidence_references','activity_documents',
             'application_options','application_option_versions','option_mappings','option_prices','status_holdings','agent_wait_goals'}
    if target_table not in allowed or status not in {'MAPPED','UNRESOLVED','REJECTED'}:
        raise ValueError('Invalid migration target or status')
    if status=='MAPPED':
        target=Base.metadata.tables[target_table]
        if target_id is None or s.scalar(select(target.c.id).where(target.c.id==target_id)) is None:
            raise ValueError('Mapped migration target must exist')
    elif target_id is not None:raise ValueError('Unresolved/rejected migration cannot claim a target')
    row=s.scalar(select(KnowledgeMigrationLink).where(KnowledgeMigrationLink.legacy_table==table,
        KnowledgeMigrationLink.legacy_id==str(identifier),KnowledgeMigrationLink.legacy_path==path,
        KnowledgeMigrationLink.migration_version==MIGRATION_VERSION))
    if row is None:
        row=KnowledgeMigrationLink(legacy_table=table,legacy_id=str(identifier),legacy_path=path,target_table=target_table,
            target_id=target_id,status=status,reason=reason,migration_version=MIGRATION_VERSION)
        s.add(row);s.flush()
    elif (row.target_table,row.target_id,row.status)!=(target_table,target_id,status):
        raise ValueError('Existing migration identity cannot be silently reassigned')
    return row


def backfill_identity_and_sources(s:Session) -> dict:
    c=CatalogService(s)
    activities=[]
    excluded_articles=0
    excluded_documents=0
    for cls,table in [(StatusEvent,"status_events"),(ArticleOpportunityRecord,"article_opportunities")]:
        for old in s.scalars(select(cls)):
            if table == 'article_opportunities':
                analysis=s.get(ArticleAnalysisRecord,old.analysis_id)
                item=s.get(SourceItem,analysis.source_item_id)
                if article_scope_reason(item):
                    excluded_articles+=1
                    continue
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
                if not mapping["source_program"].casefold().startswith(('all major ','all eligible ')):
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
        item=s.get(SourceItem,doc.source_item_id)
        if article_scope_reason(item):
            excluded_documents+=1
            continue
        from journeyplus.knowledge.sources import require_knowledge_content
        try:
            require_knowledge_content(doc)
        except ValueError as exc:
            excluded_documents+=1
            _link(s,"document_versions",doc.id,"","document_versions",None,"REJECTED",str(exc))
            continue
        section_document(s,doc.id)
        _link(s,"document_versions",doc.id,"","document_versions",doc.id,"MAPPED","Reused allowed normalized body; stable section parser")
    from journeyplus.knowledge.holding_migration import backfill_holding_links
    holding_links=backfill_holding_links(s)
    from journeyplus.knowledge.catalog_metadata import sync_catalog_metadata
    metadata=sync_catalog_metadata(s)
    s.flush()
    return {"holding_links":holding_links,"catalog_metadata":metadata,"excluded_articles":excluded_articles,"excluded_documents":excluded_documents,"activity_count":len(activities),"links":dict(s.execute(select(KnowledgeMigrationLink.status,func.count()).group_by(KnowledgeMigrationLink.status)).all()),
            "published_count":sum(s.get(Activity,UUID(x)).current_version_id is not None for x in activities)}
