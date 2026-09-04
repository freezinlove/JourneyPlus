from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from journeyplus.agent.contracts import AgentTurnResponse
from journeyplus.agent.controller import AgentController
from journeyplus.agent.waiting import WaitGoalService
from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.models import AgentInteraction
from journeyplus.product.api import create_product_app
from journeyplus.product.candidate_routes import CandidateRouteService
from tests.test_agent_waiting import _create_free_wait_goal
from tests.test_candidate_routes import _mapping_opportunity


def test_agent_page_and_unavailable_provider_do_not_break_product(
    session_factory,
) -> None:
    client = TestClient(create_product_app(session_factory))

    page = client.get("/agent")
    state = client.get("/v1/agent/state")
    turn = client.post(
        "/v1/agent/turn",
        json={"command": "MESSAGE", "message": "我有汉莎金卡"},
    )

    assert page.status_code == 200
    assert "会籍策略 Agent" in page.text
    assert state.status_code == 200
    assert state.json() == {
        "schema_version": "1",
        "available": False,
        "interaction": None,
        "wait_goal": None,
        "pending_result": None,
    }
    assert turn.status_code == 503
    assert client.get("/v1/status-holdings").status_code == 200
    script = client.get("/assets/app.js").text
    assert 'api("/v1/agent/turn"' in script
    assert 'api("/v1/agent/state")' in script
    assert "CandidateRouteService" not in script


def test_agent_api_exposes_typed_state_and_transition_errors(session_factory) -> None:
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="agent-api-question",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=0,
            challenge="No challenge",
        )
    provider = SequenceAIProvider(
        [
            {
                "action": "ASK_CLARIFICATION",
                "interpretation": {
                    "holdings": [],
                    "target": {"program": "Target Club", "tier": "Gold"},
                },
                "question": "你目前持有哪个具体项目和等级？",
                "message": "还需要一个关键信息。",
            }
        ]
    )
    client = TestClient(create_product_app(session_factory, ai_provider=provider))

    first = client.post(
        "/v1/agent/turn",
        json={"command": "MESSAGE", "message": "我想要 Target Club Gold"},
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["status"] == "AWAITING_CLARIFICATION"
    assert payload["action"] == "ASK_CLARIFICATION"
    assert payload["allowed_commands"] == ["MESSAGE", "REJECT"]

    completed = client.post(
        "/v1/agent/turn",
        json={"interaction_id": payload["interaction_id"], "command": "REJECT"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"

    invalid = client.post(
        "/v1/agent/turn",
        json={"interaction_id": payload["interaction_id"], "command": "CONFIRM"},
    )
    assert invalid.status_code == 409


def test_agent_state_cleans_expired_short_term_interactions(session_factory) -> None:
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="expired-agent-state",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=0,
            challenge="No challenge",
        )
    provider = SequenceAIProvider(
        [
            {
                "action": "ASK_CLARIFICATION",
                "interpretation": {
                    "holdings": [],
                    "target": {"program": "Target Club", "tier": "Gold"},
                },
                "question": "你持有什么会籍？",
                "message": "需要一个信息。",
            }
        ]
    )
    client = TestClient(create_product_app(session_factory, ai_provider=provider))
    created = client.post(
        "/v1/agent/turn",
        json={"command": "MESSAGE", "message": "我想要 Target Club Gold"},
    ).json()
    interaction_id = UUID(created["interaction_id"])
    with session_factory.begin() as session:
        row = session.get(AgentInteraction, interaction_id)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    state = client.get("/v1/agent/state")

    assert state.status_code == 200
    assert state.json()["interaction"] is None
    with session_factory.begin() as session:
        assert session.get(AgentInteraction, interaction_id) is None


def test_agent_provider_failure_is_isolated_from_deterministic_apis(
    session_factory,
) -> None:
    provider = SequenceAIProvider([RuntimeError("provider down")])
    client = TestClient(create_product_app(session_factory, ai_provider=provider))

    response = client.post(
        "/v1/agent/turn",
        json={"command": "MESSAGE", "message": "帮我看一条匹配路线"},
    )

    assert response.status_code == 502
    assert "模型暂时无法" in response.json()["detail"]
    assert client.get("/v1/status-holdings").status_code == 200
    assert client.get("/v1/briefs").status_code == 200


def test_wait_hit_is_returned_once_without_leaking_raw_pending_state(
    session_factory,
) -> None:
    goal = _create_free_wait_goal(session_factory)
    assert goal is not None
    with session_factory.begin() as session:
        _mapping_opportunity(
            session,
            slug="agent-api-wait-hit",
            source_program="Source Club",
            source_tier="Gold",
            target_program="Target Club",
            target_tier="Gold",
            amount=0,
            challenge="No challenge",
        )
        result = CandidateRouteService(session).query(goal.query)
        route_id = result.matching_routes[0].route_id
    provider = SequenceAIProvider(
        [
            {
                "action": "RECOMMEND",
                "primary_route_id": route_id,
                "message": "发现了符合原条件的新路线。",
            }
        ]
    )
    with session_factory.begin() as session:
        summary = WaitGoalService(session).check_current(
            lambda active_goal, result: AgentController(
                session, provider
            ).resume_wait_goal(active_goal, result)
        )
        assert summary.agent_called is True

    client = TestClient(create_product_app(session_factory, ai_provider=provider))
    first = client.get("/v1/agent/state")
    second = client.get("/v1/agent/state")

    assert first.status_code == second.status_code == 200
    assert first.json()["pending_result"]["message"] == "发现了符合原条件的新路线。"
    assert first.json()["interaction"] is None
    assert "pending_result" not in first.json()["wait_goal"]
    assert second.json()["pending_result"] is None
    assert second.json()["interaction"]["message"] == "发现了符合原条件的新路线。"


def test_database_failure_returns_typed_service_unavailable(tmp_path) -> None:
    missing_parent_url = f"sqlite+pysqlite:///{tmp_path / 'missing' / 'db.sqlite'}"
    factory = sessionmaker(bind=create_engine(missing_parent_url))
    client = TestClient(create_product_app(factory))

    response = client.get("/v1/status-holdings")

    assert response.status_code == 503
    assert "产品数据库暂不可用" in response.json()["detail"]
