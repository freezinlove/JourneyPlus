"""Alembic metadata for the selected business schema and current Agent runtime.

Historical unified ORM mappings remain importable for archived consumers, but must
never be proposed as production tables by migration autogeneration.
"""
from sqlalchemy import MetaData, Index, text, JSON
from journeyplus import models
from .storage_readiness import RUNTIME_MODELS
from .workflow_holdings import WorkflowHolding


def production_metadata():
    metadata = MetaData()
    selected = {value.__table__.name: value.__table__ for value in vars(models).values()
                if isinstance(value, type) and value.__module__ == models.__name__
                and hasattr(value, '__table__') and value not in {models.StatusHolding, models.UserBusinessOperation}}
    selected.update({model.__table__.name: model.__table__ for model in RUNTIME_MODELS})
    selected['status_holdings'] = WorkflowHolding.__table__
    for table in selected.values():
        table.to_metadata(metadata)
    metadata.tables['source_items'].c.document_role.nullable = True
    metadata.tables['agent_delivery_runs'].c.request.type = JSON()
    metadata.tables['agent_delivery_events'].c.payload.type = JSON()
    waiting = metadata.tables['agent_wait_goals']
    # Preserve the original waiting-table constraint; no new singleton restriction.
    for constraint in list(waiting.constraints):
        if constraint.name == 'ck_wait_singleton':
            waiting.constraints.remove(constraint)
    for index in list(waiting.indexes):
        if index.name == 'uq_agent_wait_goals_single_active':
            waiting.indexes.remove(index)
    Index('uq_agent_wait_goals_single_active', waiting.c.status, unique=True,
          postgresql_where=text("status = 'ACTIVE'"), sqlite_where=text("status = 'ACTIVE'"))
    return metadata
