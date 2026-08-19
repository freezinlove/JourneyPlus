from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import (
    AnalysisStage,
    RelevanceLabel,
    RelevanceResult,
    RunStatus,
)
from journeyplus.models import AnalysisRun, DocumentVersion


STATUS_RELEVANCE_PROMPT_VERSION = "status-relevance-v1"
STATUS_RELEVANCE_SCHEMA_VERSION = "1"

SYSTEM_PROMPT = """你是会籍获取机会的严格分类器。第一版只包括可直接获得、升级或延长航空、酒店或其他旅行忠诚度会籍的公开或群体公开路径，例如会籍匹配、会籍挑战、快速通道、会籍互通、付费直升、合作直接授予或延期。
信用卡或购买可以是获得会籍的资格条件；但普通信用卡资讯、买分/转分促销、常规定级积累攻略、积分票、积分房晚、单纯权益介绍都必须判为 NO。
一篇材料可包含多个独立机会，为每个机会给一个最小 event_hint。不要创建正式事件，不要补猜材料没有的信息。只输出符合给定 JSON Schema 的 JSON。"""


@dataclass(frozen=True, slots=True)
class RelevanceAnalysis:
    run: AnalysisRun
    result: RelevanceResult
    reused: bool


class StatusRelevanceAnalyzer:
    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        prompt_version: str = STATUS_RELEVANCE_PROMPT_VERSION,
        max_attempts: int = 2,
    ) -> None:
        self._session = session
        self._provider = provider
        self._prompt_version = prompt_version
        self._max_attempts = max_attempts

    def analyze(self, document: DocumentVersion) -> RelevanceAnalysis:
        key = (
            f"{AnalysisStage.STATUS_RELEVANCE}:{document.id}:"
            f"{self._provider.metadata.config_version}:{self._prompt_version}"
        )
        existing = self._session.scalar(
            select(AnalysisRun).where(AnalysisRun.idempotency_key == key)
        )
        if existing and existing.result:
            return RelevanceAnalysis(
                existing, RelevanceResult.model_validate(existing.result), True
            )

        if document.duplicate_of_id is not None:
            reusable = self._session.scalar(
                select(AnalysisRun)
                .where(
                    AnalysisRun.document_version_id == document.duplicate_of_id,
                    AnalysisRun.stage == AnalysisStage.STATUS_RELEVANCE,
                    AnalysisRun.status == RunStatus.SUCCEEDED,
                    AnalysisRun.model_config_version
                    == self._provider.metadata.config_version,
                    AnalysisRun.prompt_version == self._prompt_version,
                )
                .order_by(AnalysisRun.created_at.desc())
                .limit(1)
            )
            if reusable is not None and reusable.result:
                run = AnalysisRun(
                    idempotency_key=key,
                    document_version_id=document.id,
                    stage=AnalysisStage.STATUS_RELEVANCE,
                    status=RunStatus.SUCCEEDED,
                    input_version=str(document.id),
                    provider=self._provider.metadata.provider,
                    model=self._provider.metadata.model,
                    model_config_version=self._provider.metadata.config_version,
                    prompt_version=self._prompt_version,
                    schema_version=STATUS_RELEVANCE_SCHEMA_VERSION,
                    result=reusable.result,
                )
                self._session.add(run)
                self._session.flush()
                return RelevanceAnalysis(
                    run, RelevanceResult.model_validate(reusable.result), True
                )

        run = existing or AnalysisRun(
            idempotency_key=key,
            document_version_id=document.id,
            stage=AnalysisStage.STATUS_RELEVANCE,
            status=RunStatus.RUNNING,
            input_version=str(document.id),
            provider=self._provider.metadata.provider,
            model=self._provider.metadata.model,
            model_config_version=self._provider.metadata.config_version,
            prompt_version=self._prompt_version,
            schema_version=STATUS_RELEVANCE_SCHEMA_VERSION,
        )
        if existing is None:
            self._session.add(run)
        last_error: Exception | None = None
        result: RelevanceResult | None = None
        for _attempt in range(self._max_attempts):
            try:
                result = self._provider.generate_structured(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=f"判断以下规范化材料：\n\n{document.normalized_body}",
                    output_model=RelevanceResult,
                )
                break
            except Exception as exc:
                last_error = exc
        if result is None:
            result = RelevanceResult(
                label=RelevanceLabel.UNCERTAIN,
                confidence=0,
                reason="模型输出在有限重试后仍无法通过结构校验，等待人工复核。",
            )
            run.status = RunStatus.FAILED
            run.error = f"{type(last_error).__name__}: {last_error}"[:2000]
        else:
            run.status = RunStatus.SUCCEEDED
            run.error = None
        run.result = result.model_dump(mode="json")
        self._session.flush()
        return RelevanceAnalysis(run, result, False)
