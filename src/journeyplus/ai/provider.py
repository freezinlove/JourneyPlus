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
            metrics['io_timeout_seconds']=timeout
        response = self._client.post(
            "chat/completions",
            **request_options,
            json={
                "model": self.metadata.model,
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
        metrics['provider_request_ms']=round((monotonic()-started)*1000)
        response.raise_for_status()
        payload = response.json()
        usage=payload.get('usage')
        if isinstance(usage,dict):
            metrics['usage']={key:usage[key] for key in ('prompt_tokens','completion_tokens','total_tokens')
                              if type(usage.get(key)) is int and usage[key]>=0} or None
        content: Any = payload["choices"][0]["message"]["content"]
        if isinstance(content, str):
            content = _parse_json_content(content)
        return output_model.model_validate(content)


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
