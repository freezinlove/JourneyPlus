from __future__ import annotations

import json

import httpx

from journeyplus.ai.provider import OpenAICompatibleProvider
from journeyplus.config import Settings
from journeyplus.contracts import DocumentLabel, RelevanceResult


def test_beijing_openai_compatible_provider_uses_deepseek_and_validates_schema() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "label": "NONE",
                                    "confidence": 0.99,
                                    "reason": "ordinary points sale",
                                    "event_hints": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICompatibleProvider(
        Settings(
            ai_region="cn-beijing",
            ai_model="deepseek-v4-flash",
            ai_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            ai_api_key="test-only",
        ),
        client=client,
    )
    result = provider.generate_structured(
        system_prompt="system", user_prompt="user", output_model=RelevanceResult
    )

    assert result.label == DocumentLabel.NONE
    assert provider.metadata.region == "cn-beijing"
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in captured["messages"][0]["content"]


def test_ai_configuration_rejects_non_beijing_base_url() -> None:
    settings = Settings(
        ai_region="cn-beijing",
        ai_model="deepseek-v4-flash",
        ai_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        ai_api_key="test-only",
    )
    try:
        settings.require_ai()
    except ValueError as exc:
        assert "Beijing" in str(exc)
    else:
        raise AssertionError("A non-Beijing endpoint must be rejected")
