from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, inspect
from sqlalchemy.orm import Session, load_only

from journeyplus.membership.contracts import UnifiedMembershipNode
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.models import StatusHolding
from journeyplus.product.contracts import StatusHoldingInput, StatusHoldingView


class StatusHoldingService:
    def __init__(self, session: Session) -> None:
        self._session = session
        columns={c['name'] for c in inspect(session.connection()).get_columns('status_holdings')}
        self._original='program_id' not in columns
        if self._original:
            from journeyplus.agent.adapters.workflow_holdings import WorkflowHolding
            self._model=WorkflowHolding
        else:
            self._model=StatusHolding

    def list(self) -> list[StatusHoldingView]:
        rows = self._session.scalars(
            select(self._model).options(load_only(self._model.id,self._model.program_key,
                self._model.tier_key,self._model.program_display_name,self._model.tier_display_name,
                self._model.valid_until,self._model.created_at,self._model.updated_at)).order_by(
                self._model.program_display_name,
                self._model.tier_display_name,
            )
        )
        return [_view(row) for row in rows]

    def upsert(self, request: StatusHoldingInput) -> StatusHoldingView:
        node = self._catalog_node(request.program_key, request.tier_key)
        holding = self._session.scalar(
            select(self._model).where(
                self._model.program_key == node.program_key
            )
        )
        if holding is None:
            holding = self._model(program_key=node.program_key)
            self._session.add(holding)
        before=(holding.program_display_name,holding.tier_display_name,holding.valid_until,getattr(holding,'program_id',None),getattr(holding,'tier_id',None))
        holding.tier_key = node.tier_key
        holding.program_display_name = node.program
        holding.tier_display_name = node.tier
        holding.valid_until = request.valid_until
        self._bind_identity(holding,before)
        self._session.flush()
        return _view(holding)

    def update(self, holding_id: UUID | str, request: StatusHoldingInput) -> StatusHoldingView:
        holding = self._required(holding_id)
        node = self._catalog_node(request.program_key, request.tier_key)
        conflicting = self._session.scalar(
            select(self._model).where(
                self._model.program_key == node.program_key,
                self._model.id != holding.id,
            )
        )
        if conflicting is not None:
            self._session.delete(conflicting)
        before=(holding.program_display_name,holding.tier_display_name,holding.valid_until,getattr(holding,'program_id',None),getattr(holding,'tier_id',None))
        holding.program_key = node.program_key
        holding.tier_key = node.tier_key
        holding.program_display_name = node.program
        holding.tier_display_name = node.tier
        holding.valid_until = request.valid_until
        self._bind_identity(holding,before)
        self._session.flush()
        return _view(holding)

    def _bind_identity(self,holding,before):
        if self._original:return
        # Legacy form writes must update V2 identity and revision in the same
        # transaction; otherwise the new route evaluator keeps the previous tier.
        from journeyplus.knowledge.publication import CatalogService
        prior_revision = holding.revision or 0
        catalog=CatalogService(self._session)
        program=catalog.program(holding.program_display_name)
        tier=catalog.tier(program.id,holding.tier_display_name)
        holding.program_id=program.id;holding.tier_id=tier.id;holding.identity_status='CONFIRMED'
        after=(holding.program_display_name,holding.tier_display_name,holding.valid_until,getattr(holding,'program_id',None),getattr(holding,'tier_id',None))
        if before!=after:holding.revision=prior_revision+1

    def delete(self, holding_id: UUID | str) -> None:
        self._session.delete(self._required(holding_id))
        self._session.flush()

    def _catalog_node(self, program_key: str, tier_key: str) -> UnifiedMembershipNode:
        from journeyplus.membership.identity import resolve_identity
        identity = resolve_identity(program_key, tier_key)
        if identity['status'] == 'OK' and identity['category'] in {'AIRLINE', 'HOTEL'}:
            from journeyplus.membership.alliances import airline_alliance
            return UnifiedMembershipNode(id=identity['program_key']+'::'+identity['tier_key'],
                program_key=identity['program_key'], tier_key=identity['tier_key'],
                program=identity['program_name'], tier=identity['tier_name'],
                categories=[identity['category']], alliance=airline_alliance(identity['program_name']))
        node_id = f"{program_key}::{tier_key}"
        catalog = UnifiedMembershipTreeService(self._session).catalog()
        node = next((item for item in catalog.nodes if item.id == node_id), None)
        if node is None:
            raise LookupError(f"Unknown membership node: {node_id}")
        return node

    def _required(self, holding_id: UUID | str) -> StatusHolding:
        holding = self._session.get(self._model, UUID(str(holding_id)))
        if holding is None:
            raise LookupError(f"Status holding {holding_id} was not found")
        return holding


def _view(row: StatusHolding) -> StatusHoldingView:
    return StatusHoldingView(
        id=row.id,
        node_id=f"{row.program_key}::{row.tier_key}",
        program_key=row.program_key,
        tier_key=row.tier_key,
        program_display_name=row.program_display_name,
        tier_display_name=row.tier_display_name,
        valid_until=row.valid_until,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
