"""Agent hooks for the shared, read-only AIWorkflow knowledge projection."""
from types import SimpleNamespace
from uuid import UUID
from sqlalchemy import select
from journeyplus.memberships_validity import membership_date
from journeyplus.models import StatusHolding
from journeyplus.knowledge.workflow_knowledge import (
    WorkflowKnowledgePort as SharedWorkflowKnowledgePort,
    WorkflowActivityReader, catalog, graph_state, identity_id,
)


class WorkflowUserData:
    """Only route-source reads; current holdings schema has no unified tier FK."""
    def __init__(self, factory):
        self.factory = factory

    def route_sources(self, mode, refs=()):
        if mode != 'saved' and not refs:
            return []
        with self.factory() as session:
            statement = select(StatusHolding.id, StatusHolding.program_key, StatusHolding.tier_key,
                StatusHolding.program_display_name, StatusHolding.tier_display_name, StatusHolding.valid_until, StatusHolding.updated_at)
            if mode == 'saved':
                statement = statement.where((StatusHolding.valid_until.is_(None)) |
                    (StatusHolding.valid_until>=membership_date()))
            if refs:
                statement = statement.where(StatusHolding.id.in_([UUID(r.removeprefix('holding:')) for r in refs]))
            rows = session.execute(statement.order_by(StatusHolding.id)).mappings().all()
            from .workflow_holdings import holding_revision
            result = [{'holding_ref':'holding:'+str(r['id']), 'revision':holding_revision(SimpleNamespace(**r)),
                'tier_ref':'tier:'+str(identity_id('tier',r['program_key']+'::'+r['tier_key'])),
                'program_name':r['program_display_name'], 'tier_name':r['tier_display_name'],
                'valid_until':r['valid_until'].isoformat() if r['valid_until'] else None} for r in rows]
            found = {r['holding_ref'] for r in result}
            result.extend({'holding_ref':r,'resolution_state':'INVALID_REFERENCE','code':'STALE_REFERENCE'}
                          for r in refs if r not in found)
            return result


class WorkflowKnowledgePort(SharedWorkflowKnowledgePort):
    user_data = WorkflowUserData

    @staticmethod
    def activity_reader(session):
        return ActiveActivityReader(session)

    @property
    def memory_type(self):
        from journeyplus.agent.services.workflow_memory import WorkflowUserMemory
        return WorkflowUserMemory


class ActiveActivityReader(WorkflowActivityReader):
    def _require_active(self, identity):
        from journeyplus.models import StatusEvent, ArticleOpportunityRecord
        from journeyplus.lifecycle.visibility import is_ended
        from .activity_access import NOTICE
        record = self.session.get(StatusEvent, identity) or self.session.get(ArticleOpportunityRecord, identity)
        if record is not None and is_ended(record):
            raise LookupError(NOTICE)

    def detail(self, identity, version=None):
        self._require_active(identity)
        return super().detail(identity, version)

    def history(self, identity, **kwargs):
        self._require_active(identity)
        return super().history(identity, **kwargs)
