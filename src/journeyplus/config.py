from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from dotenv import load_dotenv


BEIJING_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = "sqlite+pysqlite:///./journeyplus.db"
    ai_provider: str = "aliyun-model-studio"
    ai_region: str = "cn-beijing"
    ai_model: str = "deepseek-v4-flash"
    ai_base_url: str | None = BEIJING_DASHSCOPE_BASE_URL
    ai_api_key: str | None = None
    ai_timeout_seconds: int = 180
    gmail_access_token: str | None = None
    gmail_client_secret_file: str = ".secrets/google-oauth-client.json"
    gmail_token_file: str = ".secrets/gmail-token.json"
    automation_source_item_limit: int = 100
    automation_document_limit: int = 20
    automation_model_call_limit: int = 100
    automation_lease_seconds: int = 3600
    knowledge_publish_enabled: bool = False
    generic_article_pipeline: str = "v2"
    generic_title_drop_enabled: bool = True
    agent_interaction_ttl_hours: int = 24
    agent_max_model_calls: int = 3
    statusmatcher_enabled: bool = False
    statusmatcher_timeout_seconds: int = 12
    statusmatcher_max_response_bytes: int = 1_000_000
    statusmatcher_max_pages: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            database_url=os.getenv(
                "JOURNEYPLUS_DATABASE_URL", "sqlite+pysqlite:///./journeyplus.db"
            ),
            ai_provider=os.getenv("JOURNEYPLUS_AI_PROVIDER", "aliyun-model-studio"),
            ai_region=os.getenv("JOURNEYPLUS_AI_REGION", "cn-beijing"),
            ai_model=os.getenv("JOURNEYPLUS_AI_MODEL", "deepseek-v4-flash"),
            ai_base_url=os.getenv(
                "JOURNEYPLUS_AI_BASE_URL", BEIJING_DASHSCOPE_BASE_URL
            ),
            ai_api_key=os.getenv("JOURNEYPLUS_AI_API_KEY"),
            ai_timeout_seconds=_positive_env_int(
                "JOURNEYPLUS_AI_TIMEOUT_SECONDS", 180
            ),
            gmail_access_token=os.getenv("JOURNEYPLUS_GMAIL_ACCESS_TOKEN"),
            gmail_client_secret_file=os.getenv(
                "JOURNEYPLUS_GMAIL_CLIENT_SECRET_FILE",
                ".secrets/google-oauth-client.json",
            ),
            gmail_token_file=os.getenv(
                "JOURNEYPLUS_GMAIL_TOKEN_FILE", ".secrets/gmail-token.json"
            ),
            automation_source_item_limit=_positive_env_int(
                "JOURNEYPLUS_AUTOMATION_SOURCE_ITEM_LIMIT", 100
            ),
            automation_document_limit=_positive_env_int(
                "JOURNEYPLUS_AUTOMATION_DOCUMENT_LIMIT", 20
            ),
            automation_model_call_limit=_positive_env_int(
                "JOURNEYPLUS_AUTOMATION_MODEL_CALL_LIMIT", 100
            ),
            automation_lease_seconds=_positive_env_int(
                "JOURNEYPLUS_AUTOMATION_LEASE_SECONDS", 3600
            ),
            knowledge_publish_enabled=_boolean_env("JOURNEYPLUS_KNOWLEDGE_PUBLISH_ENABLED", False),
            generic_article_pipeline=_choice_env(
                "JOURNEYPLUS_GENERIC_ARTICLE_PIPELINE", "v2", {"v1", "v2"}
            ),
            generic_title_drop_enabled=_boolean_env(
                "JOURNEYPLUS_GENERIC_TITLE_DROP_ENABLED", True
            ),
            agent_interaction_ttl_hours=_positive_env_int(
                "JOURNEYPLUS_AGENT_INTERACTION_TTL_HOURS", 24
            ),
            agent_max_model_calls=_bounded_env_int(
                "JOURNEYPLUS_AGENT_MAX_MODEL_CALLS", 3, maximum=3
            ),
            statusmatcher_enabled=_boolean_env(
                "JOURNEYPLUS_STATUSMATCHER_ENABLED", False
            ),
            statusmatcher_timeout_seconds=_bounded_env_int(
                "JOURNEYPLUS_STATUSMATCHER_TIMEOUT_SECONDS", 12, maximum=30
            ),
            statusmatcher_max_response_bytes=_bounded_env_int(
                "JOURNEYPLUS_STATUSMATCHER_MAX_RESPONSE_BYTES",
                1_000_000,
                maximum=1_000_000,
            ),
            statusmatcher_max_pages=_bounded_env_int(
                "JOURNEYPLUS_STATUSMATCHER_MAX_PAGES", 2, maximum=2
            ),
        )

    def require_ai(self) -> "Settings":
        if self.ai_region != "cn-beijing":
            raise ValueError("V1 requires the Aliyun Model Studio cn-beijing region")
        if self.ai_model != "deepseek-v4-flash":
            raise ValueError("V1 requires the deepseek-v4-flash model")
        if not self.ai_base_url:
            raise ValueError("A Beijing Model Studio base URL is required")
        parsed = urlsplit(self.ai_base_url)
        host = (parsed.hostname or "").casefold()
        is_beijing_host = host == "dashscope.aliyuncs.com" or host.endswith(
            ".cn-beijing.maas.aliyuncs.com"
        )
        if (
            parsed.scheme != "https"
            or not is_beijing_host
            or not parsed.path.rstrip("/").endswith("/compatible-mode/v1")
        ):
            raise ValueError(
                "V1 requires a Beijing DashScope or cn-beijing workspace "
                "OpenAI-compatible base URL"
            )
        if not self.ai_api_key:
            raise ValueError("JOURNEYPLUS_AI_API_KEY is required for live model calls")
        return self


def _positive_env_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _bounded_env_int(name: str, default: int, *, maximum: int) -> int:
    value = _positive_env_int(name, default)
    if value > maximum:
        raise ValueError(f"{name} must not exceed {maximum}")
    return value


def _choice_env(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default).strip().casefold()
    if value not in choices:
        raise ValueError(f"{name} must be one of {sorted(choices)}")
    return value


def _boolean_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")
