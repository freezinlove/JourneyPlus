from __future__ import annotations

import json
from dataclasses import dataclass
from contextvars import ContextVar
from contextlib import contextmanager
from time import monotonic
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from journeyplus.config import Settings


OutputModel = TypeVar("OutputModel", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class AIProviderMetadata:
    provider: str
    model: str
    region: str
    config_version: str


class AIProvider(Protocol):
    metadata: AIProviderMetadata

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel: ...


class OpenAICompatibleProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        settings.require_ai()
        assert settings.ai_base_url is not None
        assert settings.ai_api_key is not None
        self._temperature = temperature
        self._call_metrics = ContextVar(f'journeyplus_provider_metrics_{id(self)}',default=None)
        self._call_timeout = ContextVar(f'journeyplus_provider_timeout_{id(self)}',default=None)
        self._thinking = ContextVar(f'journeyplus_provider_thinking_{id(self)}',default=None)
        self._client = client or httpx.Client(
            base_url=settings.ai_base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {settings.ai_api_key}"},
            timeout=(
                settings.ai_timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            ),
        )
        self.metadata = AIProviderMetadata(
            provider=settings.ai_provider,
            model=settings.ai_model,
            region=settings.ai_region,
            config_version=(
                f"cn-beijing:{settings.ai_model}:temp-{temperature:g}:"
                "json-mode-pydantic-v1"
            ),
        )

    @property
    def last_call_metrics(self):
        value=self._call_metrics.get()
        return dict(value) if value is not None else None

    @contextmanager
    def thinking_mode(self, enabled: bool):
        """Request-local policy; a shared workflow client keeps its defaults."""
        token = self._thinking.set(enabled)
        try:
            yield
        finally:
            self._thinking.reset(token)

    @contextmanager
    def call_timeout(self,seconds):
        if seconds<=0:raise TimeoutError('Provider call budget exhausted')
        token=self._call_timeout.set(seconds)
        try:yield
        finally:self._call_timeout.reset(token)

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        schema_json=json.dumps(output_model.model_json_schema(),ensure_ascii=False)
        metrics={'schema_bytes':len(schema_json.encode()),'system_prompt_bytes':len(system_prompt.encode()),
                 'user_prompt_bytes':len(user_prompt.encode()),'usage':None}
        self._call_metrics.set(metrics)
        started=monotonic()
        timeout=self._call_timeout.get()
        request_options={}
        if timeout is not None:
            settings=self._client.timeout.as_dict()
            request_options['timeout']=httpx.Timeout(**{k:min(v,timeout) if v is not None else timeout for k,v in settings.items()})
        effective_timeout=request_options.get('timeout',self._client.timeout)
        metrics['io_timeouts_seconds']=effective_timeout.as_dict()
        metrics['io_timeout_seconds']=effective_timeout.read
        thinking=self._thinking.get()
        metrics['enable_thinking']=thinking
        try:
            response = self._client.post(
                "chat/completions",
                **request_options,
                json={
                    "model": self.metadata.model,
                    **({'enable_thinking':thinking} if thinking is not None else {}),
                    "temperature": self._temperature,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                f"{system_prompt}\n\n"
                                "必须只返回一个 JSON 对象，不要使用 Markdown 代码块，并严格符合"
                                "以下 JSON Schema；服务端 JSON Mode 只保证合法 JSON，字段仍由"
                                "本地 Schema 校验：\n"
                                + schema_json
                            ),
                        },
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
        finally:
            metrics['provider_request_ms']=round((monotonic()-started)*1000)
        response.raise_for_status()
        payload = response.json()
        metrics['response_model']=payload.get('model')
        usage=payload.get('usage')
        if isinstance(usage,dict):
            metrics['usage']={key:usage[key] for key in ('prompt_tokens','completion_tokens','total_tokens')
                              if type(usage.get(key)) is int and usage[key]>=0} or None
            for section,key in (('completion_tokens_details','reasoning_tokens'),('prompt_tokens_details','cached_tokens')):
                value=usage.get(section,{})
                if isinstance(value,dict) and type(value.get(key)) is int and value[key]>=0:
                    metrics[key]=value[key]
        content: Any = payload["choices"][0]["message"]["content"]
        if isinstance(content, str):
            content = _parse_json_content(content)
        return output_model.model_validate(content)


    def stream_text(self, *, system_prompt: str, user_prompt: str):
        """Yield actual provider content deltas; never expose reasoning_content."""
        started=monotonic()
        metrics={'schema_bytes':0,'system_prompt_bytes':len(system_prompt.encode()),
                 'user_prompt_bytes':len(user_prompt.encode()),'usage':None,'enable_thinking':False,'stream':True}
        self._call_metrics.set(metrics)
        remaining=self._call_timeout.get()
        timeout=httpx.Timeout(**{k:min(v,remaining) if v is not None and remaining is not None else remaining if v is None else v
                                for k,v in self._client.timeout.as_dict().items()})
        metrics['io_timeouts_seconds']=timeout.as_dict();metrics['io_timeout_seconds']=timeout.read
        done=False;finish_reason=None
        try:
            with self._client.stream('POST','chat/completions',timeout=timeout,json={
                'model':self.metadata.model,'temperature':self._temperature,'enable_thinking':False,
                'stream':True,'stream_options':{'include_usage':True},
                'messages':[{'role':'system','content':system_prompt},{'role':'user','content':user_prompt}]
            }) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if remaining is not None and monotonic()-started>=remaining:raise TimeoutError('MODEL_STREAM_DEADLINE')
                    if not line.startswith('data:'):continue
                    raw=line[5:].strip()
                    if raw=='[DONE]':
                        done=True;break
                    payload=json.loads(raw)
                    metrics.setdefault('first_event_ms',round((monotonic()-started)*1000))
                    metrics['response_model']=payload.get('model',metrics.get('response_model'))
                    usage=payload.get('usage')
                    if isinstance(usage,dict):
                        metrics['usage']={k:usage[k] for k in ('prompt_tokens','completion_tokens','total_tokens') if type(usage.get(k)) is int}
                        for section,key in (('completion_tokens_details','reasoning_tokens'),('prompt_tokens_details','cached_tokens')):
                            details=usage.get(section) or {}
                            if type(details.get(key)) is int:metrics[key]=details[key]
                    for choice in payload.get('choices',[]):
                        if choice.get('finish_reason') is not None:
                            finish_reason=choice['finish_reason'];metrics['finish_reason']=finish_reason
                        delta=choice.get('delta',{}).get('content')
                        if delta:
                            metrics.setdefault('first_content_ms',round((monotonic()-started)*1000))
                            yield delta
            if not done or finish_reason not in (None,'stop'):
                raise RuntimeError('MODEL_STREAM_INCOMPLETE')
        finally:
            metrics['provider_request_ms']=round((monotonic()-started)*1000)


def _parse_json_content(content: str) -> Any:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1])
        if stripped.lstrip().startswith("json"):
            stripped = stripped.lstrip()[4:].lstrip()
    return json.loads(stripped)


class SequenceAIProvider:
    """Deterministic provider for contracts, gold evaluation, and replay tests."""

    def __init__(self, responses: list[dict[str, Any] | BaseModel | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.metadata = AIProviderMetadata(
            provider="test",
            model="sequence",
            region="local",
            config_version="sequence-v1",
        )

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "schema": output_model.model_json_schema(),
            }
        )
        if not self._responses:
            raise RuntimeError("No configured AI response remains")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return output_model.model_validate(response)
