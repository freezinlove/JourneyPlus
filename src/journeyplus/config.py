from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = "sqlite+pysqlite:///./journeyplus.db"
    ai_provider: str = "aliyun-model-studio"
    ai_region: str = "cn-beijing"
    ai_model: str = "deepseek-v4-flash"
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    gmail_access_token: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv(
                "JOURNEYPLUS_DATABASE_URL", "sqlite+pysqlite:///./journeyplus.db"
            ),
            ai_provider=os.getenv("JOURNEYPLUS_AI_PROVIDER", "aliyun-model-studio"),
            ai_region=os.getenv("JOURNEYPLUS_AI_REGION", "cn-beijing"),
            ai_model=os.getenv("JOURNEYPLUS_AI_MODEL", "deepseek-v4-flash"),
            ai_base_url=os.getenv("JOURNEYPLUS_AI_BASE_URL"),
            ai_api_key=os.getenv("JOURNEYPLUS_AI_API_KEY"),
            gmail_access_token=os.getenv("JOURNEYPLUS_GMAIL_ACCESS_TOKEN"),
        )

    def require_ai(self) -> "Settings":
        if self.ai_region != "cn-beijing":
            raise ValueError("V1 requires the Aliyun Model Studio cn-beijing region")
        if self.ai_model != "deepseek-v4-flash":
            raise ValueError("V1 requires the deepseek-v4-flash model")
        if not self.ai_base_url or ".cn-beijing.maas.aliyuncs.com" not in self.ai_base_url:
            raise ValueError("A cn-beijing Model Studio workspace base URL is required")
        if not self.ai_api_key:
            raise ValueError("JOURNEYPLUS_AI_API_KEY is required for live model calls")
        return self

