from __future__ import annotations

import pytest

from journeyplus.agent.controller import AgentController
from journeyplus.agent.statusmatcher import StatusMatcherExperienceClient
from journeyplus.ai.provider import SequenceAIProvider
from journeyplus.config import Settings


def test_agent_runtime_defaults_are_bounded(monkeypatch) -> None:
    for name in (
        "JOURNEYPLUS_AGENT_MAX_MODEL_CALLS",
        "JOURNEYPLUS_STATUSMATCHER_ENABLED",
        "JOURNEYPLUS_STATUSMATCHER_TIMEOUT_SECONDS",
        "JOURNEYPLUS_STATUSMATCHER_MAX_RESPONSE_BYTES",
        "JOURNEYPLUS_STATUSMATCHER_MAX_PAGES",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.agent_max_model_calls == 3
    assert settings.statusmatcher_enabled is False
    assert settings.statusmatcher_timeout_seconds == 12
    assert settings.statusmatcher_max_response_bytes == 1_000_000
    assert settings.statusmatcher_max_pages == 2


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JOURNEYPLUS_AGENT_MAX_MODEL_CALLS", "4"),
        ("JOURNEYPLUS_STATUSMATCHER_TIMEOUT_SECONDS", "31"),
        ("JOURNEYPLUS_STATUSMATCHER_MAX_RESPONSE_BYTES", "1000001"),
        ("JOURNEYPLUS_STATUSMATCHER_MAX_PAGES", "3"),
    ],
)
def test_agent_runtime_rejects_limits_above_product_boundary(
    monkeypatch, name, value
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match="must not exceed"):
        Settings.from_env()


def test_runtime_components_reject_unbounded_direct_configuration(
    db_session,
) -> None:
    with pytest.raises(ValueError, match="between 1 and 3"):
        AgentController(db_session, SequenceAIProvider([]), max_model_calls=4)
    with pytest.raises(ValueError, match="between 1 and 2"):
        StatusMatcherExperienceClient(max_pages=3)
