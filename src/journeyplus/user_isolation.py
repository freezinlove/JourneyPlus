"""One ORM scope for both holding mappings and workspace owners.

HTTP establishes the identity; recovered tasks restore it from their workspace.
Only maintenance uses acting_as(None). No model argument can change this scope.
"""
from sqlalchemy import event,inspect
from sqlalchemy.orm import Session,with_loader_criteria
from journeyplus.user_scope import _current
from journeyplus.models import StatusHolding,AgentInteraction,UserBusinessOperation
from journeyplus.agent.adapters.workflow_holdings import WorkflowHolding

SCOPED=(StatusHolding,WorkflowHolding,AgentInteraction,UserBusinessOperation)

@event.listens_for(Session,'do_orm_execute')
def scope_query(state):
    uid=_current.get()
    if uid is None:return
    if state.is_select:
        for model in SCOPED:
            state.statement=state.statement.options(with_loader_criteria(model,model.user_id==uid,include_aliases=True))
    elif state.is_update or state.is_delete:
        table=state.statement.table
        if table.name in {m.__tablename__ for m in SCOPED}:
            state.statement=state.statement.where(table.c.user_id==uid)

@event.listens_for(Session,'before_flush')
def scope_writes(session,context,instances):
    uid=_current.get()
    if uid is None:return
    for row in session.new|session.dirty|session.deleted:
        if isinstance(row,SCOPED):
            if row in session.new and row.user_id is None:row.user_id=uid
            if row.user_id!=uid or (row not in session.new and inspect(row).attrs.user_id.history.has_changes()):
                raise PermissionError('Cross-user write denied')
