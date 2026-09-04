from __future__ import annotations

from journeyplus.agent.contracts import (
    AgentAction,
    AgentCommand,
    AgentTurnRequest,
    AgentTurnResponse,
    WaitCheckStatus,
)
from journeyplus.agent.controller import AgentController
from journeyplus.agent.waiting import WaitGoalService
from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.product.candidate_routes import CandidateRouteService
from journeyplus.product.contracts import CandidateRouteQuery, CandidateTarget, StatusHoldingInput
from journeyplus.product.holdings import StatusHoldingService
from tests.test_agent_controller import _interpretation
from tests.test_candidate_routes import _mapping_opportunity


def _create_free_wait_goal(session_factory, *, research: bool = False):
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="paid-before-wait",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=149,
            challenge="No challenge",
        )
        StatusHoldingService(session).upsert(
            StatusHoldingInput(program_key="source club", tier_key="gold")
        )
        route_id = CandidateRouteService(session).query(
            CandidateRouteQuery(target=CandidateTarget(program_key="target club"))
        ).matching_routes[0].route_id
    interpretation = _interpretation(research=research)
    interpretation["action"] = "QUERY_CANDIDATES"
    interpretation["interpretation"]["constraints"] = {"cost_policy": "FREE_ONLY"}
    provider = SequenceAIProvider(
        [
            interpretation,
            {
                "action": "PROPOSE_ADJUSTMENT",
                "adjustment": {
                    "condition": "cost_policy",
                    "new_value": "ANY",
                    "route_id": route_id,
                    "explanation": "接受付费路线。",
                },
                "message": "是否接受付费路线？",
            },
            {
                "action": "OFFER_WAITING",
                "message": "是否保持免费条件持续跟进？",
            },
        ]
    )
    with session_factory.begin() as session:
        first = AgentController(session, provider).turn(
            AgentTurnRequest(message="我只等免费路线")
        )
    with session_factory.begin() as session:
        AgentController(session, provider).turn(
            AgentTurnRequest(
                interaction_id=first.interaction_id,
                command=AgentCommand.REJECT,
            )
        )
    with session_factory.begin() as session:
        AgentController(session, provider).turn(
            AgentTurnRequest(
                interaction_id=first.interaction_id,
                command=AgentCommand.CONFIRM,
            )
        )
        return WaitGoalService(session).current()


def test_wait_check_uses_no_agent_until_first_new_hit_and_deduplicates(
    session_factory,
) -> None:
    goal = _create_free_wait_goal(session_factory)
    assert goal is not None
    callback_calls = []

    def resume(_goal, result):
        callback_calls.append(result.matching_signature)
        return AgentTurnResponse(
            action=AgentAction.RECOMMEND,
            message="发现第一条符合免费条件的新路线。",
            candidate_result=result,
            primary_route=result.matching_routes[0],
        )

    with session_factory.begin() as session:
        no_hit = WaitGoalService(session).check_current(resume)
    assert no_hit.status == WaitCheckStatus.NO_HIT
    assert no_hit.agent_called is False
    assert callback_calls == []

    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="free-after-wait",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=0,
            challenge="No challenge",
        )

    with session_factory.begin() as session:
        hit = WaitGoalService(session).check_current(resume)
    assert hit.status == WaitCheckStatus.HIT
    assert hit.agent_called is True
    assert len(callback_calls) == 1

    with session_factory.begin() as session:
        duplicate = WaitGoalService(session).check_current(resume)
        pending = WaitGoalService(session).consume_pending()
        consumed_again = WaitGoalService(session).consume_pending()
    assert duplicate.status == WaitCheckStatus.DUPLICATE
    assert len(callback_calls) == 1
    assert pending is not None
    assert pending.primary_route is not None
    assert consumed_again is None
    with session_factory.begin() as session:
        current = WaitGoalService(session).current()
        assert current is not None
        assert current.pending_seen_at is not None


def test_wait_goal_cancel_stops_future_checks(session_factory) -> None:
    _create_free_wait_goal(session_factory)
    with session_factory.begin() as session:
        response = AgentController(session, SequenceAIProvider([])).turn(
            AgentTurnRequest(command=AgentCommand.CANCEL_WAIT)
        )
        assert response.wait_goal is not None
        assert response.wait_goal.status == "CANCELLED"
        summary = WaitGoalService(session).check_current(
            lambda _goal, _result: (_ for _ in ()).throw(AssertionError())
        )
    assert summary.status == WaitCheckStatus.NO_GOAL


def test_wait_goal_can_be_explicitly_finished(session_factory) -> None:
    _create_free_wait_goal(session_factory)
    with session_factory.begin() as session:
        response = AgentController(session, SequenceAIProvider([])).turn(
            AgentTurnRequest(command=AgentCommand.FINISH_WAIT)
        )
        assert response.wait_goal is not None
        assert response.wait_goal.status == "COMPLETED"
        assert WaitGoalService(session).current() is None


def test_wait_hit_failure_does_not_advance_signature(session_factory) -> None:
    _create_free_wait_goal(session_factory)
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="free-for-retry",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=0,
            challenge="No challenge",
        )
    with session_factory.begin() as session:
        failed = WaitGoalService(session).check_current(
            lambda _goal, _result: (_ for _ in ()).throw(RuntimeError("model down"))
        )
        current = WaitGoalService(session).current()
    assert failed.status == WaitCheckStatus.FAILED
    assert current is not None
    with session_factory.begin() as session:
        assert WaitGoalService(session).consume_pending() is None

    with session_factory.begin() as session:
        retry = WaitGoalService(session).check_current(
            lambda _goal, result: AgentTurnResponse(
                action=AgentAction.RECOMMEND,
                message="retry worked",
                candidate_result=result,
                primary_route=result.matching_routes[0],
            )
        )
    assert retry.status == WaitCheckStatus.HIT
