"""Narrow read-version fingerprints; immutable continuations need no rescans."""
import hashlib
import json
from datetime import datetime, UTC
from sqlalchemy import select
from journeyplus.knowledge.models import Activity, ActivityKnowledgeVersion, MembershipProgram, MembershipTier, MembershipAlias, ActivityObservationState, ApplicationOptionVersion
from journeyplus.models import StatusHolding, AgentWaitGoal


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


def snapshot_for(name, knowledge, factory):
    if name not in {'catalog.lookup','activity.read','routes.evaluate','holdings.read','holdings.write','waiting.manage'}:
        return None

    def snapshot(args, context):
        raw=args.model_dump(mode='json')
        selector=raw.get('selector',{}).get('ref','')
        if (raw.get('cursor') or name=='routes.evaluate' and raw.get('operation') in {'inspect','compare'}
            or name=='activity.read' and (selector.startswith('artifact:') or '@' in selector or raw.get('version_ref'))):
            return fingerprint([name,raw])
        values=[]
        if name in {'catalog.lookup','activity.read','routes.evaluate'}:
            with knowledge.read() as session:
                if hasattr(knowledge,'snapshot_values'):
                    values.append(knowledge.snapshot_values(session,name))
                else:
                    statements=[
                        select(MembershipProgram.id,MembershipProgram.updated_at,MembershipProgram.canonical_key,
                               MembershipProgram.display_name,MembershipProgram.category,MembershipProgram.alliance),
                        select(MembershipTier.id,MembershipTier.updated_at,MembershipTier.program_id,
                               MembershipTier.canonical_key,MembershipTier.display_name,MembershipTier.rank),
                        select(MembershipAlias.id,MembershipAlias.updated_at,MembershipAlias.program_id,
                               MembershipAlias.tier_id,MembershipAlias.normalized_alias,MembershipAlias.locale,MembershipAlias.origin)]
                    if name!='catalog.lookup':
                        statements.extend([
                            select(Activity.id,Activity.updated_at,Activity.current_version_id,Activity.merged_into_id,
                                   Activity.primary_program_id,Activity.kind),
                            select(ActivityKnowledgeVersion.id,ActivityKnowledgeVersion.status,ActivityKnowledgeVersion.fact_hash)
                                .join(Activity,Activity.current_version_id==ActivityKnowledgeVersion.id)])
                    for statement in statements:
                        # Include the whole set of narrow keys: deletions and status
                        # transitions cannot disappear behind MAX(updated_at).
                        values.append(sorted((tuple(row) for row in session.execute(statement)),key=lambda row:str(row[0])))
                    if name!='catalog.lookup':
                        values.append([tuple(row) for row in session.execute(select(
                            ActivityObservationState.activity_id,ActivityObservationState.freshness,
                            ActivityObservationState.last_checked_at,ActivityObservationState.last_source_changed_at
                        ).order_by(ActivityObservationState.activity_id))])
                    if name=='routes.evaluate':
                        from journeyplus.knowledge.routes import window_state
                        now=datetime.now(UTC)
                        windows=list(session.execute(select(ApplicationOptionVersion.id,ApplicationOptionVersion.application_window)
                            .join(ActivityKnowledgeVersion,ApplicationOptionVersion.knowledge_version_id==ActivityKnowledgeVersion.id)
                            .join(Activity,Activity.current_version_id==ActivityKnowledgeVersion.id)))
                        windows+=list(session.execute(select(ActivityKnowledgeVersion.id,ActivityKnowledgeVersion.facts['application_window'])
                            .join(Activity,Activity.current_version_id==ActivityKnowledgeVersion.id)))
                        values.append(sorted([(str(key),window_state(window or {},now)) for key,window in windows]))
                        values.append(now.date().isoformat())
        query=raw.get('query')
        query=query if isinstance(query,dict) else {}
        sources=query.get('sources') or {}
        read_holdings=name in {'holdings.read','holdings.write'} or name=='routes.evaluate' and (
            sources.get('mode')=='saved' or sources.get('holding_refs') or raw.get('query_ref'))
        if read_holdings or name=='waiting.manage':
            from journeyplus.agent.adapters.transactions import read_session
            with read_session(factory) as session:
                if read_holdings:
                    values.append(datetime.now(UTC).date().isoformat())
                    if hasattr(knowledge,'holding_snapshot'):
                        values.append(knowledge.holding_snapshot(session))
                    else:
                        values.append([tuple(row) for row in session.execute(select(StatusHolding.id,StatusHolding.revision,StatusHolding.updated_at).order_by(StatusHolding.id))])
                if name=='waiting.manage':
                    values.append([tuple(row) for row in session.execute(select(AgentWaitGoal.id,AgentWaitGoal.revision,AgentWaitGoal.status).order_by(AgentWaitGoal.id))])
        return fingerprint(values)
    return snapshot
