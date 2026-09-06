from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.membership.contracts import UnifiedMembershipNode
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.models import StatusHolding
from journeyplus.product.contracts import StatusHoldingInput, StatusHoldingView


class StatusHoldingService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[StatusHoldingView]:
        rows = self._session.scalars(
            select(StatusHolding).order_by(
                StatusHolding.program_display_name,
                StatusHolding.tier_display_name,
            )
        )
        return [_view(row) for row in rows]

    def upsert(self, request: StatusHoldingInput) -> StatusHoldingView:
        node = self._catalog_node(request.program_key, request.tier_key)
        holding = self._session.scalar(
            select(StatusHolding).where(
                StatusHolding.program_key == node.program_key
            )
        )
        if holding is None:
            holding = StatusHolding(program_key=node.program_key)
            self._session.add(holding)
        before=(holding.program_display_name,holding.tier_display_name,holding.valid_until,holding.program_id,holding.tier_id)
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
            select(StatusHolding).where(
                StatusHolding.program_key == node.program_key,
                StatusHolding.id != holding.id,
            )
        )
        if conflicting is not None:
            self._session.delete(conflicting)
        before=(holding.program_display_name,holding.tier_display_name,holding.valid_until,holding.program_id,holding.tier_id)
        holding.program_key = node.program_key
        holding.tier_key = node.tier_key
        holding.program_display_name = node.program
        holding.tier_display_name = node.tier
        holding.valid_until = request.valid_until
        self._bind_identity(holding,before)
        self._session.flush()
        return _view(holding)

    def _bind_identity(self,holding,before):
        # Legacy form writes must update V2 identity and revision in the same
        # transaction; otherwise the new route evaluator keeps the previous tier.
        from journeyplus.knowledge.publication import CatalogService
        prior_revision = holding.revision or 0
        catalog=CatalogService(self._session)
        program=catalog.program(holding.program_display_name)
        tier=catalog.tier(program.id,holding.tier_display_name)
        holding.program_id=program.id;holding.tier_id=tier.id;holding.identity_status='CONFIRMED'
        after=(holding.program_display_name,holding.tier_display_name,holding.valid_until,holding.program_id,holding.tier_id)
        if before!=after:holding.revision=prior_revision+1

    def delete(self, holding_id: UUID | str) -> None:
        self._session.delete(self._required(holding_id))
        self._session.flush()

    def _catalog_node(self, program_key: str, tier_key: str) -> UnifiedMembershipNode:
        node_id = f"{program_key}::{tier_key}"
        catalog = UnifiedMembershipTreeService(self._session).catalog()
        node = next((item for item in catalog.nodes if item.id == node_id), None)
        if node is None:
            raise LookupError(f"Unknown membership node: {node_id}")
        return node

    def _required(self, holding_id: UUID | str) -> StatusHolding:
        holding = self._session.get(StatusHolding, UUID(str(holding_id)))
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
