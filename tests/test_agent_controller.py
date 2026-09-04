from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from journeyplus.agent.contracts import (
    AgentAction,
    AgentCommand,
    AgentTurnRequest,
    ExperienceAvailability,
    StatusMatcherObservation,
)
from journeyplus.agent.controller import AgentController, AgentStateError
from journeyplus.agent.waiting import WaitGoalService
from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.models import AgentInteraction, StatusHolding
from journeyplus.product.candidate_routes import CandidateRouteService
from journeyplus.product.contracts import (
    CandidateRouteQuery,
    CandidateTarget,
    StatusHoldingInput,
)
from journeyplus.product.holdings import StatusHoldingService
from tests.test_candidate_routes import _mapping_opportunity


def _interpretation(*, research: bool = False) -> dict:
    return {
        "action": "CONFIRM_HOLDINGS",
        "interpretation": {
            "holdings": [{"program": "Source Club", "tier": "Gold"}],
            "target": {"program": "Target Club", "tier": "Gold"},
            "preferences": ["步骤少"],
            "research_statusmatcher": research,
        },
        "message": "已理解请求",
    }


def _seed_route(session_factory, *, amount: int = 0) -> str:
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug=f"target-{amount}",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=amount,
            challenge="No challenge",
        )
    with session_factory.begin() as session:
        StatusHoldingService(session).upsert(
            StatusHoldingInput(program_key="source club", tier_key="gold")
        )
        result = CandidateRouteService(session).query(
            CandidateRouteQuery(
                target=CandidateTarget(
                    program_key="target club", tier_key="gold"
                )
            )
        )
        return result.matching_routes[0].route_id


def test_new_holding_requires_confirmation_before_persisting(session_factory) -> None:
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="confirm-route",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=0,
            challenge="No challenge",
        )
    with session_factory.begin() as session:
        preview = CandidateRouteService(session).query(
            CandidateRouteQuery(
                target=CandidateTarget(program_key="target club", tier_key="gold")
            ),
            holding_node_ids=[],
        )
        assert preview.matching_routes == []

    provider = SequenceAIProvider(
        [
            _interpretation(),
            {
                "action": "RECOMMEND",
                "primary_route_id": "placeholder",
                "message": "这条免费直达路线最符合你的取舍。",
                "risks": ["联盟等级等价未结构化时需自行核对"],
            },
        ]
    )
    with session_factory.begin() as session:
        controller = AgentController(session, provider)
        first = controller.turn(AgentTurnRequest(message="我有 Source Club Gold，想要 Target Club Gold"))
        assert first.action == AgentAction.CONFIRM_HOLDINGS
        assert StatusHoldingService(session).list() == []
        interaction_id = first.interaction_id

    with session_factory.begin() as session:
        route_id = CandidateRouteService(session).query(
            CandidateRouteQuery(target=CandidateTarget(program_key="target club")),
            holding_node_ids=[],
        ).matching_routes
        assert route_id == []
        record = session.get(AgentInteraction, interaction_id)
        assert record is not None

    with session_factory.begin() as session:
        # Route ids are deterministic; replace the replay placeholder after the holding exists
        holding = StatusHoldingService(session).upsert(
            StatusHoldingInput(program_key="source club", tier_key="gold")
        )
        route_id = CandidateRouteService(session).query(
            CandidateRouteQuery(target=CandidateTarget(program_key="target club"))
        ).matching_routes[0].route_id
        session.delete(session.get(StatusHolding, holding.id))
        provider._responses[0]["primary_route_id"] = route_id

    with session_factory.begin() as session:
        second = AgentController(session, provider).turn(
            AgentTurnRequest(
                interaction_id=interaction_id,
                command=AgentCommand.CONFIRM,
            )
        )
        assert second.action == AgentAction.RECOMMEND
        assert second.primary_route is not None
        assert second.primary_route.route_id == route_id
        assert StatusHoldingService(session).list()[0].node_id == "source club::gold"
def test_existing_holding_can_go_directly_to_recommendation(session_factory) -> None:
    route_id = _seed_route(session_factory)
    interpretation = _interpretation()
    interpretation["action"] = "QUERY_CANDIDATES"
    provider = SequenceAIProvider(
        [
            interpretation,
            {
                "action": "RECOMMEND",
                "primary_route_id": route_id,
                "message": "直接选择当前路线。",
                "risks": ["申请后无法退款。", "申请前核对官方费用。"],
            },
        ]
    )
    with session_factory.begin() as session:
        response = AgentController(session, provider).turn(
            AgentTurnRequest(message="用我已有的 Source Club Gold 匹配 Target Club")
        )
    assert response.action == AgentAction.RECOMMEND
    assert response.risks == ["申请前核对官方费用。"]
    assert len(provider.calls) == 2


def test_unknown_route_is_explained_without_being_recommended(session_factory) -> None:
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="unknown-route",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=None,
            challenge=None,
        )
        StatusHoldingService(session).upsert(
            StatusHoldingInput(program_key="source club", tier_key="gold")
        )
    interpretation = _interpretation()
    interpretation["action"] = "QUERY_CANDIDATES"
    interpretation["interpretation"]["constraints"] = {
        "cost_policy": "FREE_ONLY"
    }
    provider = SequenceAIProvider(
        [
            interpretation,
            {
                "action": "COMPLETE",
                "message": "费用没有明确证据，不能把它当作免费可行路线。",
                "risks": ["当前申请路线的费用未知。"],
            },
        ]
    )

    with session_factory.begin() as session:
        response = AgentController(session, provider).turn(
            AgentTurnRequest(message="只接受免费的 Target Club 路线")
        )

    assert response.action == AgentAction.COMPLETE
    assert response.primary_route is None
    assert response.candidate_result is not None
    assert response.candidate_result.unknown_routes
    assert response.risks == ["当前申请路线的费用未知。"]


def test_provider_failure_after_confirmed_holding_keeps_write_and_degrades(
    session_factory,
) -> None:
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="degraded-after-confirmation",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=0,
            challenge="No challenge",
        )
    provider = SequenceAIProvider([_interpretation(), RuntimeError("provider down")])
    with session_factory.begin() as session:
        first = AgentController(session, provider).turn(
            AgentTurnRequest(message="我有 Source Club Gold，想要 Target Club Gold")
        )
    with session_factory.begin() as session:
        degraded = AgentController(session, provider).turn(
            AgentTurnRequest(
                interaction_id=first.interaction_id,
                command=AgentCommand.CONFIRM,
            )
        )
        holdings = StatusHoldingService(session).list()

    assert degraded.status == "FAILED"
    assert degraded.primary_route is None
    assert degraded.candidate_result is not None
    assert len(holdings) == 1


def test_illegal_strategy_action_is_rejected(session_factory) -> None:
    route_id = _seed_route(session_factory)
    interpretation = _interpretation()
    interpretation["action"] = "QUERY_CANDIDATES"
    provider = SequenceAIProvider(
        [
            interpretation,
            {
                "action": "PROPOSE_ADJUSTMENT",
                "adjustment": {
                    "condition": "cost_policy",
                    "new_value": "ALLOW_FEE",
                    "route_id": route_id,
                    "explanation": "非法动作",
                },
                "message": "非法动作",
            },
        ]
    )
    with session_factory.begin() as session:
        with pytest.raises(AgentStateError, match="不允许"):
            AgentController(session, provider).turn(
                AgentTurnRequest(message="推荐一条路线")
            )


class _ExperienceResearcher:
    enabled = True

    def research(self, route):
        return StatusMatcherObservation(
            availability=ExperienceAvailability.INSUFFICIENT,
            route_id=route.route_id,
            observed_at=datetime.now(UTC),
            signal="证据不足",
            limitation="测试样本不足",
        )


def test_research_path_obeys_three_call_budget(session_factory) -> None:
    route_id = _seed_route(session_factory)
    interpretation = _interpretation(research=True)
    interpretation["action"] = "QUERY_CANDIDATES"
    provider = SequenceAIProvider(
        [
            interpretation,
            {
                "action": "RESEARCH_EXPERIENCE",
                "selected_research_route_ids": [route_id],
                "message": "先核对经验",
            },
            {
                "action": "RECOMMEND",
                "primary_route_id": route_id,
                "alternative_route_ids": None,
                "selected_research_route_ids": None,
                "message": "结合正式事实，仍推荐这条路线。",
                "risks": None,
            },
        ]
    )
    with session_factory.begin() as session:
        response = AgentController(
            session,
            provider,
            max_model_calls=3,
            experience_researcher=_ExperienceResearcher(),
        ).turn(AgentTurnRequest(message="请查真实经验后推荐"))
    assert response.action == AgentAction.RECOMMEND
    assert len(response.experience) == 1
    assert len(provider.calls) == 3
    final_prompt = json.loads(provider.calls[2]["user_prompt"])
    assert len(final_prompt["candidate_observation"]["matching_routes"]) == 1

    provider = SequenceAIProvider(
        [
            interpretation,
            {
                "action": "RESEARCH_EXPERIENCE",
                "selected_research_route_ids": [route_id],
                "message": "先核对经验",
            },
        ]
    )
    with session_factory.begin() as session:
        with pytest.raises(AgentStateError, match="达到上限"):
            AgentController(
                session,
                provider,
                max_model_calls=2,
                experience_researcher=_ExperienceResearcher(),
            ).turn(AgentTurnRequest(message="请查真实经验后推荐"))


def test_explicit_research_request_cannot_be_silently_skipped(session_factory) -> None:
    route_id = _seed_route(session_factory)
    interpretation = _interpretation(research=True)
    interpretation["action"] = "QUERY_CANDIDATES"
    provider = SequenceAIProvider(
        [
            interpretation,
            {
                "action": "RECOMMEND",
                "primary_route_id": route_id,
                "message": "试图跳过已明确要求的经验调查。",
            },
        ]
    )

    with session_factory.begin() as session:
        with pytest.raises(AgentStateError, match="不允许"):
            AgentController(
                session,
                provider,
                experience_researcher=_ExperienceResearcher(),
            ).turn(AgentTurnRequest(message="请查真实经验后推荐"))


def test_no_solution_proposes_one_adjustment_then_offers_waiting(session_factory) -> None:
    route_id = _seed_route(session_factory, amount=149)
    interpretation = _interpretation()
    interpretation["action"] = "QUERY_CANDIDATES"
    interpretation["interpretation"]["constraints"] = {
        "cost_policy": "FREE_ONLY",
        "challenge_policy": "ALLOW",
    }
    provider = SequenceAIProvider(
        [
            interpretation,
            {
                "action": "PROPOSE_ADJUSTMENT",
                "adjustment": {
                    "condition": "cost_policy",
                    "new_value": "ANY",
                    "route_id": route_id,
                    "explanation": "接受 USD 149 可解锁当前路线。",
                },
                "message": "当前没有免费路线；是否接受这一条付费路线？",
            },
            {
                "action": "OFFER_WAITING",
                "message": "保持免费条件继续等待可以吗？",
            },
        ]
    )
    with session_factory.begin() as session:
        first = AgentController(session, provider).turn(
            AgentTurnRequest(message="我只接受免费的 Target Club 路线")
        )
        assert first.action == AgentAction.PROPOSE_ADJUSTMENT
        assert first.proposed_adjustment is not None
        assert first.candidate_result is not None
        assert first.candidate_result.nearby_routes[0].violations == ["cost_policy"]

    with session_factory.begin() as session:
        second = AgentController(session, provider).turn(
            AgentTurnRequest(
                interaction_id=first.interaction_id,
                command=AgentCommand.REJECT,
            )
        )
        assert second.action == AgentAction.OFFER_WAITING
        assert second.allowed_commands == [
            AgentCommand.CONFIRM,
            AgentCommand.MESSAGE,
            AgentCommand.REJECT,
        ]

    with session_factory.begin() as session:
        final = AgentController(session, provider).turn(
            AgentTurnRequest(
                interaction_id=first.interaction_id,
                command=AgentCommand.CONFIRM,
            )
        )
        goal = WaitGoalService(session).current()
        assert final.wait_goal is not None
        assert final.wait_goal.id == goal.id
        assert goal is not None
        assert goal.query.constraints.cost_policy == "FREE_ONLY"
        assert len(provider.calls) == 3


def test_confirmed_adjustment_requeries_only_changed_condition(session_factory) -> None:
    route_id = _seed_route(session_factory, amount=149)
    interpretation = _interpretation()
    interpretation["action"] = "QUERY_CANDIDATES"
    interpretation["interpretation"]["constraints"] = {
        "cost_policy": "FREE_ONLY"
    }
    provider = SequenceAIProvider(
        [
            interpretation,
            {
                "action": "PROPOSE_ADJUSTMENT",
                "adjustment": {
                    "condition": "cost_policy",
                    "new_value": "ALLOW_FEE",
                    "route_id": route_id,
                    "explanation": "放宽免费要求。",
                },
                "message": "是否放宽免费要求？",
            },
            {
                "action": "RECOMMEND",
                "primary_route_id": route_id,
                "message": "放宽后这条路线可行。",
            },
        ]
    )
    with session_factory.begin() as session:
        first = AgentController(session, provider).turn(
            AgentTurnRequest(message="只要免费路线")
        )
    with session_factory.begin() as session:
        final = AgentController(session, provider).turn(
            AgentTurnRequest(
                interaction_id=first.interaction_id,
                command=AgentCommand.CONFIRM,
            )
        )
    assert final.action == AgentAction.RECOMMEND
    assert final.primary_route is not None
