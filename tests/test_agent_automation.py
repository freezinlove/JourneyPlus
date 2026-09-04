from __future__ import annotations

from datetime import UTC, datetime

from journeyplus.agent.contracts import (
    ExperienceAvailability,
    StatusMatcherObservation,
    WaitCheckStatus,
)
from journeyplus.agent.waiting import WaitGoalService
from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.automation.service import AutomationLimits, run_daily_cycle
from journeyplus.models import AgentWaitGoal
from journeyplus.product.candidate_routes import CandidateRouteService
from tests.test_agent_waiting import _create_free_wait_goal
from tests.test_candidate_routes import _mapping_opportunity


def _unused_adapter(_source_id: str):
    raise AssertionError("no source adapter should run")


def test_daily_wait_check_makes_zero_model_calls_without_hit(session_factory) -> None:
    _create_free_wait_goal(session_factory)
    provider = SequenceAIProvider([])

    result = run_daily_cycle(
        session_factory,
        provider,
        _unused_adapter,
        source_ids=[],
        now=datetime(2026, 9, 4, 1, tzinfo=UTC),
    )

    assert result.agent_wait_status == WaitCheckStatus.NO_HIT
    assert result.agent_wait_model_called is False
    assert result.model_calls == len(provider.calls) == 0
    with session_factory.begin() as session:
        assert WaitGoalService(session).current() is not None


def test_daily_first_hit_resumes_agent_once(session_factory) -> None:
    _create_free_wait_goal(session_factory)
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="daily-free-hit",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=0,
            challenge="No challenge",
        )
        goal = WaitGoalService(session).current()
        assert goal is not None
        candidate = CandidateRouteService(session).query(goal.query)
        route_id = candidate.matching_routes[0].route_id
    provider = SequenceAIProvider(
        [
            {
                "action": "RECOMMEND",
                "primary_route_id": route_id,
                "message": "出现了符合原条件的新路线。",
            }
        ]
    )

    result = run_daily_cycle(
        session_factory,
        provider,
        _unused_adapter,
        source_ids=[],
        now=datetime(2026, 9, 5, 1, tzinfo=UTC),
    )

    assert result.agent_wait_status == WaitCheckStatus.HIT
    assert result.agent_wait_model_called is True
    assert result.agent_wait_matching_count >= 1
    assert result.model_calls == len(provider.calls) == 1
    with session_factory.begin() as session:
        goal = WaitGoalService(session).current()
        assert goal is not None
        row = session.get(AgentWaitGoal, goal.id)
        assert row is not None
        assert row.pending_result is not None


class _Researcher:
    enabled = True

    def research(self, route):
        return StatusMatcherObservation(
            availability=ExperienceAvailability.INSUFFICIENT,
            route_id=route.route_id,
            observed_at=datetime.now(UTC),
            signal="证据不足",
            limitation="测试样本不足",
        )


def test_daily_wait_hit_does_not_advance_when_model_budget_runs_out(
    session_factory,
) -> None:
    goal = _create_free_wait_goal(session_factory, research=True)
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="daily-research-budget-hit",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=0,
            challenge="No challenge",
        )
        candidate = CandidateRouteService(session).query(goal.query)
        route_id = candidate.matching_routes[0].route_id
    provider = SequenceAIProvider(
        [
            {
                "action": "RESEARCH_EXPERIENCE",
                "selected_research_route_ids": [route_id],
                "message": "先调查经验。",
            }
        ]
    )

    result = run_daily_cycle(
        session_factory,
        provider,
        _unused_adapter,
        source_ids=[],
        now=datetime(2026, 9, 6, 1, tzinfo=UTC),
        limits=AutomationLimits(model_calls=1),
        agent_experience_researcher=_Researcher(),
    )

    assert result.agent_wait_status == WaitCheckStatus.FAILED
    assert result.agent_wait_model_called is False
    with session_factory.begin() as session:
        row = session.get(AgentWaitGoal, goal.id)
        assert row is not None
        assert row.last_candidate_signature is None
        assert row.pending_result is None
