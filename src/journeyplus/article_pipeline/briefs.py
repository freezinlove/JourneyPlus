from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.briefs.service import (
    SYSTEM_PROMPT,
    BriefGenerator,
    _allowed_source_links,
    _correction_action,
    _fact_key_availability,
    _normalize_brief_output,
    _safe_error_message,
)
from journeyplus.contracts import AnalysisStage, Brief, FactSet, RunStatus
from journeyplus.models import (
    AnalysisRun,
    ArticleAnalysisRecord,
    ArticleBriefRecord,
    ArticleOpportunityRecord,
)


ARTICLE_BRIEF_PROMPT_VERSION = "generic-article-brief-v1"
ARTICLE_BRIEF_SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ArticleBriefGeneration:
    run: AnalysisRun
    record: ArticleBriefRecord
    brief: Brief
    reused: bool


class ArticleBriefGenerator:
    """Second and final normal-path AI call, fed only persisted article facts."""

    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        prompt_version: str = ARTICLE_BRIEF_PROMPT_VERSION,
        max_attempts: int = 2,
    ) -> None:
        self._session = session
        self._provider = provider
        self._prompt_version = prompt_version
        self._max_attempts = max_attempts

    def generate(self, opportunity: ArticleOpportunityRecord) -> ArticleBriefGeneration:
        fact_set = FactSet.model_validate(opportunity.facts)
        key = (
            f"{AnalysisStage.ARTICLE_BRIEF}:{opportunity.id}:"
            f"{opportunity.fact_signature}:{self._provider.metadata.config_version}:"
            f"{self._prompt_version}"
        )
        existing = self._session.scalar(
            select(AnalysisRun).where(AnalysisRun.idempotency_key == key)
        )
        if existing is not None and existing.result:
            record = self._session.scalar(
                select(ArticleBriefRecord)
                .where(ArticleBriefRecord.analysis_run_id == existing.id)
                .order_by(ArticleBriefRecord.version.desc())
            )
            if record is not None:
                return ArticleBriefGeneration(
                    existing, record, Brief.model_validate(record.content), True
                )

        analysis = self._session.get(ArticleAnalysisRecord, opportunity.analysis_id)
        if analysis is None:
            raise LookupError("Article analysis was not found")
        run = existing or AnalysisRun(
            idempotency_key=key,
            document_version_id=analysis.document_version_id,
            stage=AnalysisStage.ARTICLE_BRIEF,
            status=RunStatus.RUNNING,
            input_version=opportunity.fact_signature,
            provider=self._provider.metadata.provider,
            model=self._provider.metadata.model,
            model_config_version=self._provider.metadata.config_version,
            prompt_version=self._prompt_version,
            schema_version=ARTICLE_BRIEF_SCHEMA_VERSION,
        )
        if existing is None:
            self._session.add(run)
        self._session.flush()

        known_fact_keys, unknown_fact_keys = _fact_key_availability(fact_set)
        allowed_source_links = _allowed_source_links(fact_set)
        last_error: Exception | None = None
        brief: Brief | None = None
        for _attempt in range(self._max_attempts):
            request_payload = {
                "fact_set_id": str(opportunity.id),
                "fact_set": opportunity.facts,
                "known_fact_keys": known_fact_keys,
                "unknown_fact_keys": unknown_fact_keys,
                "allowed_source_links": allowed_source_links,
                "editorial_rules": [
                    "只能使用持久化事实，不能读取或引用原始正文",
                    "只能引用 known_fact_keys",
                    "unknown_fact_keys 必须从文案和 fact_keys 中省略",
                ],
            }
            if last_error is not None:
                request_payload["correction"] = {
                    "previous_attempt_rejected_for": _safe_error_message(last_error),
                    "required_action": _correction_action(last_error),
                }
            try:
                candidate = self._provider.generate_structured(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(request_payload, ensure_ascii=False),
                    output_model=Brief,
                )
                candidate = _normalize_brief_output(candidate, fact_set)
                BriefGenerator._validate(candidate, opportunity, fact_set)
                brief = candidate
                break
            except Exception as exc:
                last_error = exc
        if brief is None:
            run.status = RunStatus.FAILED
            run.error = (
                f"Brief generation failed after {self._max_attempts} attempts: "
                f"{_safe_error_message(last_error or ValueError('unknown error'))}"
            )[:4000]
            self._session.flush()
            raise ValueError(run.error) from last_error

        run.status = RunStatus.SUCCEEDED
        run.result = brief.model_dump(mode="json")
        run.error = None
        version = (
            self._session.scalar(
                select(func.max(ArticleBriefRecord.version)).where(
                    ArticleBriefRecord.opportunity_id == opportunity.id
                )
            )
            or 0
        ) + 1
        record = ArticleBriefRecord(
            opportunity_id=opportunity.id,
            analysis_run_id=run.id,
            input_version=opportunity.fact_signature,
            version=version,
            schema_version=brief.schema_version,
            content=brief.model_dump(mode="json"),
        )
        self._session.add(record)
        self._session.flush()
        opportunity.current_brief_id = record.id
        self._session.flush()
        return ArticleBriefGeneration(run, record, brief, False)
