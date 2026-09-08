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


def test_agent_thinking_policy_is_scoped_and_metrics_preserve_usage_details():
    bodies=[]
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200,json={'model':'deepseek-v4-flash','usage':{
            'prompt_tokens':12,'completion_tokens':4,'total_tokens':16,
            'completion_tokens_details':{'reasoning_tokens':0},'prompt_tokens_details':{'cached_tokens':8}},
            'choices':[{'message':{'content':json.dumps({'label':'NONE','confidence':1,'reason':'ok','event_hints':[]})}}]})
    client=httpx.Client(base_url='https://example.com/',timeout=5,transport=httpx.MockTransport(handler))
    p=OpenAICompatibleProvider(Settings(ai_api_key='test-only'),client=client)
    with p.thinking_mode(False),p.call_timeout(90):
        p.generate_structured(system_prompt='test',user_prompt='test',output_model=RelevanceResult)
    assert bodies[0]['enable_thinking'] is False
    assert p.last_call_metrics['io_timeout_seconds']==5
    assert p.last_call_metrics['reasoning_tokens']==0
    assert p.last_call_metrics['cached_tokens']==8
    p.generate_structured(system_prompt='test',user_prompt='test',output_model=RelevanceResult)
    assert 'enable_thinking' not in bodies[1]
    client.close()


def test_stream_records_first_content_and_ignores_reasoning():
    chunks=[{'choices':[{'delta':{'reasoning_content':'not visible'}}]},
            {'model':'deepseek-v4-flash','choices':[{'delta':{'content':'你好。'}}]},
            {'choices':[],'usage':{'prompt_tokens':5,'completion_tokens':3,'total_tokens':8}}]
    def handler(request):
        body=json.loads(request.content)
        assert body['stream'] and body['enable_thinking'] is False
        return httpx.Response(200,text=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n')
    p=OpenAICompatibleProvider(Settings(ai_api_key='test'),client=httpx.Client(base_url='https://example.com/',transport=httpx.MockTransport(handler)))
    assert list(p.stream_text(system_prompt='test',user_prompt='hello'))==['你好。']
    assert p.last_call_metrics['first_content_ms']>=0
    assert p.last_call_metrics['usage']['total_tokens']==8


def test_stream_rejects_truncation_after_preserving_actual_deltas():
    import pytest
    for ending in ('', 'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\ndata: [DONE]\n\n'):
        body='data: {"choices":[{"delta":{"content":"已收到。"}}]}\n\n'+ending
        with httpx.Client(base_url='https://example.com/',transport=httpx.MockTransport(lambda request:httpx.Response(200,text=body))) as client:
            p=OpenAICompatibleProvider(Settings(ai_api_key='test'),client=client)
            stream=p.stream_text(system_prompt='test',user_prompt='test')
            assert next(stream)=='已收到。'
            with pytest.raises(RuntimeError,match='MODEL_STREAM_INCOMPLETE'):next(stream)
            assert p.last_call_metrics['provider_request_ms']>=0


def test_failed_structured_request_keeps_actual_duration():
    import pytest
    def timeout(request):raise httpx.ReadTimeout('test')
    with httpx.Client(base_url='https://example.com/',transport=httpx.MockTransport(timeout)) as client:
        p=OpenAICompatibleProvider(Settings(ai_api_key='test'),client=client)
        with pytest.raises(httpx.ReadTimeout):p.generate_structured(system_prompt='test',user_prompt='test',output_model=RelevanceResult)
        assert p.last_call_metrics['provider_request_ms']>=0
        assert p.last_call_metrics['usage'] is None
