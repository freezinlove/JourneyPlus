from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from journeyplus.agent.contracts import (
    AgentAction,
    AgentTurnRequest,
    ExperienceAvailability,
    StatusMatcherObservation,
    StrategyDecision,
)
from journeyplus.product.contracts import (
    CandidateConstraints,
    CandidateCostPolicy,
    CandidateTarget,
)


def test_candidate_target_and_maximum_are_strict() -> None:
    with pytest.raises(ValidationError):
        CandidateTarget()
    with pytest.raises(ValidationError):
        CandidateTarget(tier_key="gold", alliance="天合联盟")
    with pytest.raises(ValidationError):
        CandidateConstraints(
            cost_policy=CandidateCostPolicy.MAX_AMOUNT,
            max_amount=100,
        )


def test_agent_turn_message_and_recommendation_bounds_are_strict() -> None:
    with pytest.raises(ValidationError):
        AgentTurnRequest(message="")
    with pytest.raises(ValidationError):
        StrategyDecision(
            action=AgentAction.RECOMMEND,
            message="选择这条路线",
        )
    with pytest.raises(ValidationError):
        StrategyDecision(
            action=AgentAction.RECOMMEND,
            primary_route_id="primary",
            alternative_route_ids=["a", "b", "c"],
            message="too many",
        )


def test_statusmatcher_observation_has_bounded_reports() -> None:
    payload = {
        "availability": ExperienceAvailability.INSUFFICIENT,
        "route_id": "route",
        "observed_at": datetime.now(UTC),
        "signal": "证据不足",
        "limitation": "没有可比报告",
        "reports": [
            {
                "outcome": "OTHER",
                "source_program": "Source",
                "target_program": "Target",
                "summary": str(index),
            }
            for index in range(21)
        ],
    }
    with pytest.raises(ValidationError):
        StatusMatcherObservation.model_validate(payload)
