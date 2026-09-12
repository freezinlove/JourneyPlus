import asyncio
import copy
import json

import httpx
import pytest

from journeyplus.agent.adapters.config import AgentConfig
from journeyplus.agent.adapters.model import AgentModel, cache_messages, wire_messages
from journeyplus.agent.harness.contracts import ModelMessage, Part
from tests.test_harness_model import native_response


def test_cache_boundaries_preserve_prefix_text_and_call_pairing():
    messages = [
        {'role': 'system', 'content': 'Stable instructions'},
        {'role': 'user', 'content': 'Original question'},
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call'}]},
        {'role': 'tool', 'tool_call_id': 'call', 'content': '{"amount":"199"}'},
    ]
    original = copy.deepcopy(messages)
    first = cache_messages(messages)
    second = cache_messages(messages + [{'role': 'user', 'content': 'Follow-up'}])
    assert messages == original
    for message in second:
        assert not isinstance(message['content'], str)
    assert first[2] == original[2]
    assert first[3]['tool_call_id'] == 'call'
    assert first[0] == second[0]
    assert first[1:3] == second[1:3]
    assert first[3]['content'][0]['text'] == second[3]['content'][0]['text']
    assert 'cache_control' not in second[3]['content'][0]
    assert sum('cache_control' in block for m in second for block in m['content'] or []) == 2


@pytest.mark.parametrize('protocol', ['native', 'json'])
@pytest.mark.parametrize('enabled', [False, True])
def test_explicit_cache_is_sent_and_usage_survives_both_protocols(protocol, enabled):
    async def scenario():
        payloads = []
        usage = {'prompt_tokens': 2000, 'completion_tokens': 10,
                 'prompt_tokens_details': {'cached_tokens': 1500, 'cache_creation_input_tokens': 100}}
        def respond(request):
            payloads.append(json.loads(request.content))
            if protocol == 'native':
                return native_response([
                    {'choices': [{'delta': {'content': '费用是 199 欧元。'}, 'finish_reason': 'stop'}]},
                    {'choices': [], 'usage': usage}])
            return httpx.Response(200, json={'usage': usage, 'choices': [{'finish_reason': 'stop',
                'message': {'content': json.dumps({'message': '费用是 199 欧元。', 'finished': True})}}]})
        client = httpx.AsyncClient(base_url='https://test/', transport=httpx.MockTransport(respond))
        config = AgentConfig('test', 'https://test/', '', 32768, explicit_cache=enabled)
        model = AgentModel(config, client)
        model.protocol = protocol
        messages = [ModelMessage(role='system', content=[Part(type='text', text='Use actual tool facts.')]),
                    ModelMessage(role='user', content=[Part(type='text', text='费用是多少？')])]
        events = [e async for e in model.stream(messages, [], {}, asyncio.Event())]
        assert [e.text for e in events if e.type == 'text_delta'] == ['费用是 199 欧元。']
        assert next(e.usage for e in events if e.type == 'usage') == usage
        assert model.metrics[-1]['usage'] == usage
        assert model.metrics[-1]['explicit_cache'] == enabled
        if enabled:
            assert payloads[0]['messages'][-1]['content'][0]['cache_control'] == {'type': 'ephemeral'}
        else:
            assert 'cache_control' not in json.dumps(payloads[0])
        if protocol == 'native':
            assert 'response_format' not in payloads[0]
            assert payloads[0]['messages'] == (cache_messages(wire_messages(messages)) if enabled else wire_messages(messages))
        await model.close()
    asyncio.run(scenario())


def test_prompt_cache_setting_is_explicit_and_changes_configuration_identity(monkeypatch):
    monkeypatch.setenv('JOURNEYPLUS_AGENT_CONTEXT_WINDOW', '32768')
    monkeypatch.setenv('JOURNEYPLUS_AGENT_EXPLICIT_CACHE', 'true')
    assert AgentConfig.from_env().explicit_cache is True
    monkeypatch.setenv('JOURNEYPLUS_AGENT_EXPLICIT_CACHE', 'false')
    assert AgentConfig.from_env().explicit_cache is False
    async def scenario():
        a = AgentModel(AgentConfig('test', 'https://test/', '', 32768, explicit_cache=False))
        b = AgentModel(AgentConfig('test', 'https://test/', '', 32768, explicit_cache=True))
        assert a.configuration_id != b.configuration_id
        await a.close()
        await b.close()
    asyncio.run(scenario())
