"""Read-version fingerprints for generic no-progress detection."""
import hashlib
import json
from sqlalchemy import select
from journeyplus.knowledge.models import Activity, ActivityKnowledgeVersion, MembershipProgram, MembershipTier, MembershipAlias
from journeyplus.models import StatusHolding, AgentWaitGoal


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


def snapshot_for(name, knowledge, factory):
    """Immutable artifact inputs already identify their own snapshot in arguments."""
    if name not in {'catalog.lookup','activity.read','routes.evaluate','holdings.read','holdings.write','waiting.manage'}:
        return None

    def snapshot(args, context):
        values=[]
        if name in {'catalog.lookup','activity.read','routes.evaluate'}:
            with knowledge.read() as session:
                for model in (Activity,ActivityKnowledgeVersion,MembershipProgram,MembershipTier,MembershipAlias):
                    # Include catalogue edits and publication status transitions,
                    # not unrelated Agent messages or generated receipt IDs.
                    rows=session.execute(select(model.__table__)).mappings()
                    values.append(sorted((dict(row) for row in rows),key=lambda row:str(row['id'])))
        if name in {'routes.evaluate','holdings.read','holdings.write','waiting.manage'}:
            with factory() as session:
                values.append([tuple(row) for row in session.execute(select(StatusHolding.id,StatusHolding.revision,StatusHolding.updated_at).order_by(StatusHolding.id))])
                if name=='waiting.manage':
                    values.append([tuple(row) for row in session.execute(select(AgentWaitGoal.id,AgentWaitGoal.revision,AgentWaitGoal.status).order_by(AgentWaitGoal.id))])
        return fingerprint(values)
    return snapshot
