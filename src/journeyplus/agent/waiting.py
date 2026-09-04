from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.agent.contracts import (
    AgentInteractionState,
    AgentInteractionStatus,
    AgentTurnResponse,
    AgentWaitGoalStatus,
    AgentWaitGoalView,
    WaitCheckStatus,
    WaitCheckSummary,
)
from journeyplus.models import AgentWaitGoal
from journeyplus.product.candidate_routes import CandidateRouteService
from journeyplus.product.contracts import CandidateRouteQuery, CandidateRouteResult
from journeyplus.product.holdings import StatusHoldingService


class WaitGoalError(RuntimeError):
    pass


class WaitGoalService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def current(self) -> AgentWaitGoalView | None:
        row = self._current_row()
        return _view(row) if row is not None else None

    def create_from_confirmed_interaction(
        self,
        state: AgentInteractionState,
        *,
        interaction_id,
    ) -> AgentWaitGoalView:
        if (
            state.status != AgentInteractionStatus.AWAITING_WAIT_CONFIRMATION
            or not state.adjustment_attempted
            or state.query is None
            or state.interpretation is None
            or (
                state.candidate_result is not None
                and state.candidate_result.matching_routes
            )
        ):
            raise WaitGoalError(
                "等待目标只能在无方案、完成一次调整流程并得到用户确认后创建。"
            )
        current = self._current_row()
        if current is not None:
            current.status = AgentWaitGoalStatus.REPLACED
            self._session.flush()
        holdings = StatusHoldingService(self._session).list()
        row = AgentWaitGoal(
            source_interaction_id=interaction_id,
            status=AgentWaitGoalStatus.ACTIVE,
            query=state.query.model_dump(mode="json"),
            preferences=state.interpretation.preferences,
            research_statusmatcher=state.interpretation.research_statusmatcher,
            holding_node_ids=[item.node_id for item in holdings],
        )
        self._session.add(row)
        self._session.flush()
        return _view(row)

    def cancel(self) -> AgentWaitGoalView:
        row = self._required_current()
        row.status = AgentWaitGoalStatus.CANCELLED
        self._session.flush()
        return _view(row)

    def finish(self) -> AgentWaitGoalView:
        row = self._required_current()
        row.status = AgentWaitGoalStatus.COMPLETED
        self._session.flush()
        return _view(row)

    def consume_pending(self) -> AgentTurnResponse | None:
        row = self._current_row()
        if row is None or row.pending_result is None or row.pending_seen_at is not None:
            return None
        response = AgentTurnResponse.model_validate(row.pending_result)
        row.pending_result = None
        row.pending_seen_at = datetime.now(UTC)
        self._session.flush()
        return response

    def check_current(
        self,
        resume_agent: Callable[
            [AgentWaitGoalView, CandidateRouteResult], AgentTurnResponse
        ],
    ) -> WaitCheckSummary:
        row = self._current_row()
        if row is None:
            return WaitCheckSummary(status=WaitCheckStatus.NO_GOAL)
        try:
            query = CandidateRouteQuery.model_validate(row.query)
            result = CandidateRouteService(self._session).query(
                query,
                holding_node_ids=row.holding_node_ids,
            )
            if not result.matching_routes:
                return WaitCheckSummary(
                    status=WaitCheckStatus.NO_HIT,
                    goal_id=row.id,
                )
            if result.matching_signature == row.last_candidate_signature:
                return WaitCheckSummary(
                    status=WaitCheckStatus.DUPLICATE,
                    goal_id=row.id,
                    matching_count=len(result.matching_routes),
                )
            with self._session.begin_nested():
                response = resume_agent(_view(row), result)
            row.pending_result = response.model_dump(mode="json")
            row.pending_seen_at = None
            row.notified_at = datetime.now(UTC)
            row.last_candidate_signature = result.matching_signature
            self._session.flush()
            return WaitCheckSummary(
                status=WaitCheckStatus.HIT,
                goal_id=row.id,
                matching_count=len(result.matching_routes),
                agent_called=True,
            )
        except Exception as exc:
            return WaitCheckSummary(
                status=WaitCheckStatus.FAILED,
                goal_id=row.id,
                error=f"{type(exc).__name__}: {str(exc)[:900]}",
            )

    def _current_row(self) -> AgentWaitGoal | None:
        return self._session.scalar(
            select(AgentWaitGoal)
            .where(AgentWaitGoal.status == AgentWaitGoalStatus.ACTIVE)
            .order_by(AgentWaitGoal.updated_at.desc(), AgentWaitGoal.id.desc())
            .limit(1)
        )

    def _required_current(self) -> AgentWaitGoal:
        row = self._current_row()
        if row is None:
            raise WaitGoalError("当前没有持续跟进目标。")
        return row


def _view(row: AgentWaitGoal) -> AgentWaitGoalView:
    return AgentWaitGoalView(
        id=row.id,
        status=AgentWaitGoalStatus(row.status),
        query=CandidateRouteQuery.model_validate(row.query),
        preferences=list(row.preferences),
        research_statusmatcher=row.research_statusmatcher,
        pending_seen_at=row.pending_seen_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
