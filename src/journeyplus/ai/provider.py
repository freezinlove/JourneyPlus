from __future__ import annotations

import json
from dataclasses import dataclass
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
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        settings.require_ai()
        assert settings.ai_base_url is not None
        assert settings.ai_api_key is not None
        self._temperature = temperature
        self._client = client or httpx.Client(
            base_url=settings.ai_base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {settings.ai_api_key}"},
            timeout=timeout_seconds,
        )
        self.metadata = AIProviderMetadata(
            provider=settings.ai_provider,
            model=settings.ai_model,
            region=settings.ai_region,
            config_version=f"cn-beijing:{settings.ai_model}:temp-{temperature:g}:v1",
        )

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        response = self._client.post(
            "chat/completions",
            json={
                "model": self.metadata.model,
                "temperature": self._temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        payload = response.json()
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

