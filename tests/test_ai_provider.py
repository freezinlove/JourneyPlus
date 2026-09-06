from __future__ import annotations

import json

import httpx

from journeyplus.ai.provider import OpenAICompatibleProvider
from journeyplus.config import Settings
from journeyplus.contracts import DocumentLabel, RelevanceResult


def test_per_call_io_timeout_is_clamped_and_does_not_change_shared_client():
    from pydantic import BaseModel
    class Result(BaseModel):ok:bool
    observed=[]
    def handler(request):
        observed.append(request.extensions['timeout'])
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}]})
    client=httpx.Client(base_url='https://example.com/',timeout=10,transport=httpx.MockTransport(handler))
    provider=OpenAICompatibleProvider(Settings(ai_region='cn-beijing',ai_model='deepseek-v4-flash',ai_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',ai_api_key='test-only'),client=client)
    with provider.call_timeout(0.75):provider.generate_structured(system_prompt='system',user_prompt='user',output_model=Result)
    provider.generate_structured(system_prompt='system',user_prompt='user',output_model=Result)
    assert set(observed[0].values())=={0.75}
    assert set(observed[1].values())=={10}


def test_beijing_openai_compatible_provider_uses_deepseek_and_validates_schema() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "usage":{"prompt_tokens":123,"completion_tokens":17,"total_tokens":140},
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
    assert provider.last_call_metrics['usage']=={'prompt_tokens':123,'completion_tokens':17,'total_tokens':140}
    assert provider.last_call_metrics['user_prompt_bytes']==4


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


def test_provider_uses_configured_timeout_for_large_structured_results() -> None:
    provider = OpenAICompatibleProvider(
        Settings(
            ai_region="cn-beijing",
            ai_model="deepseek-v4-flash",
            ai_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            ai_api_key="test-only",
            ai_timeout_seconds=180,
        )
    )
    try:
        assert provider._client.timeout.read == 180
    finally:
        provider._client.close()


def test_provider_usage_is_isolated_between_concurrent_callers():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier=Barrier(2)
    def handler(request):
        value=int(json.loads(request.content)['messages'][1]['content'])
        return httpx.Response(200,json={'usage':{'prompt_tokens':value},'choices':[{'message':{'content':json.dumps(
            {'label':'NONE','confidence':0.9,'reason':'test','event_hints':[]})}}]})
    client=httpx.Client(base_url='https://dashscope.aliyuncs.com/compatible-mode/v1/',transport=httpx.MockTransport(handler))
    provider=OpenAICompatibleProvider(Settings(ai_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',ai_api_key='test-only'),client=client)
    def call(value):
        provider.generate_structured(system_prompt='test',user_prompt=str(value),output_model=RelevanceResult)
        barrier.wait(timeout=5)
        return provider.last_call_metrics['usage']['prompt_tokens']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(call,[11,22]))==[11,22]
    assert provider.last_call_metrics is None
    client.close()
