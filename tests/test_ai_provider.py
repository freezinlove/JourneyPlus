from __future__ import annotations

import json

import httpx

from journeyplus.ai.provider import OpenAICompatibleProvider
from journeyplus.config import Settings
from journeyplus.contracts import RelevanceLabel, RelevanceResult


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
                                    "label": "NO",
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
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenAICompatibleProvider(
        Settings(
            ai_region="cn-beijing",
            ai_model="deepseek-v4-flash",
            ai_base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/",
            ai_api_key="test-only",
        ),
        client=client,
    )
    result = provider.generate_structured(
        system_prompt="system", user_prompt="user", output_model=RelevanceResult
    )

    assert result.label == RelevanceLabel.NO
    assert provider.metadata.region == "cn-beijing"
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["response_format"] == {"type": "json_object"}

