from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from journeyplus.ai.provider import OpenAICompatibleProvider
from journeyplus.config import Settings


class AISmokeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    message: str = Field(min_length=1, max_length=80)


def run_ai_smoke(settings: Settings | None = None) -> AISmokeResponse:
    provider = OpenAICompatibleProvider(settings or Settings.from_env())
    return provider.generate_structured(
        system_prompt=(
            "这是最小连通性测试。不要使用工具，不要联网，不要输出额外事实。"
        ),
        user_prompt='返回 {"ok": true, "message": "连接成功"} 的同义 JSON。',
        output_model=AISmokeResponse,
    )

