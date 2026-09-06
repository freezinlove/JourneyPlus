from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.article_pipeline.contracts import (
    TitleScreenBatch,
    TitleScreenDecision,
    TitleScreenResult,
)
from journeyplus.contracts import AnalysisStage, RunStatus
from journeyplus.models import AnalysisRun, DocumentVersion, SourceItem


TITLE_SCREEN_PROMPT_VERSION = "generic-title-screen-v1"
TITLE_SCREEN_SCHEMA_VERSION = "1"

SYSTEM_PROMPT = """你是旅行会籍机会文章的高召回标题预筛器。输入中每项只有稳定 ID 和标题。
逐项返回：
- PASS：标题明确是可直接获得、升级、匹配、挑战、快速通道、付费直升、延期会籍，或精英定级进度促销；
- DROP：标题明确与上述内容无关，例如普通积分、折扣、航班、休息室体验、信用卡常规资讯。只有非常确定时才 DROP；
- NEEDS_BODY：标题含糊、可能需要上下文，或无法可靠判断。
不得假定你看过正文，不得补猜标题没有的信息。必须原样返回每个 document_version_id，不能遗漏、重复或增加项目。只输出 JSON。"""


@dataclass(frozen=True, slots=True)
class ScreeningOutcome:
    run: AnalysisRun
    result: TitleScreenResult
    reused: bool


class BatchTitleScreener:
    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        prompt_version: str = TITLE_SCREEN_PROMPT_VERSION,
        batch_size: int = 25,
        confidence_floor: float = 0.80,
        drop_confidence_floor: float = 0.90,
    ) -> None:
        if batch_size < 1 or batch_size > 50:
            raise ValueError("batch_size must be between 1 and 50")
        self._session = session
        self._provider = provider
        self._prompt_version = prompt_version
        self._batch_size = batch_size
        self._confidence_floor = confidence_floor
        self._drop_confidence_floor = drop_confidence_floor

    def screen(self, documents: list[DocumentVersion], *, rendered=None) -> list[ScreeningOutcome]:
        if not documents:
            return []
        document_ids = [document.id for document in documents]
        items = {
            item.id: item
            for item in self._session.scalars(
                select(SourceItem).where(
                    SourceItem.id.in_(document.source_item_id for document in documents)
                )
            )
        }
        if len(items) != len({document.source_item_id for document in documents}):
            raise LookupError("One or more source items were not found")

        by_document_id: dict[object, ScreeningOutcome] = {}
        pending: list[tuple[DocumentVersion, SourceItem, AnalysisRun]] = []
        for document in documents:
            item = items[document.source_item_id]
            key = self._idempotency_key(document, item)
            existing = self._session.scalar(
                select(AnalysisRun).where(AnalysisRun.idempotency_key == key)
            )
            if existing is not None and existing.result:
                result = self._normalize_result(
                    TitleScreenResult.model_validate(existing.result)
                )
                by_document_id[document.id] = ScreeningOutcome(existing, result, True)
                continue
            run = existing or AnalysisRun(
                idempotency_key=key,
                document_version_id=document.id,
                stage=AnalysisStage.ARTICLE_TITLE_SCREENING,
                status=RunStatus.RUNNING,
                input_version=f"{document.id}:{_title_signature(item.title)}",
                provider=self._provider.metadata.provider,
                model=self._provider.metadata.model,
                model_config_version=self._provider.metadata.config_version,
                prompt_version=self._prompt_version,
                schema_version=TITLE_SCREEN_SCHEMA_VERSION,
            )
            if existing is None:
                self._session.add(run)
            pending.append((document, item, run))
        self._session.flush()

        for start in range(0, len(pending), self._batch_size):
            chunk = pending[start : start + self._batch_size]
            outcomes = self._screen_chunk(chunk, rendered=rendered)
            by_document_id.update({outcome.result.document_version_id: outcome for outcome in outcomes})

        return [by_document_id[document_id] for document_id in document_ids]

    def _screen_chunk(
        self, chunk: list[tuple[DocumentVersion, SourceItem, AnalysisRun]], *, rendered=None
    ) -> list[ScreeningOutcome]:
        if rendered is None:
            results,error = self.render_chunk(chunk)
        else:
            results = {document.id:rendered[document.id][0] for document,_,_ in chunk}
            error = next((rendered[document.id][1] for document,_,_ in chunk if rendered[document.id][1]),None)
        outcomes: list[ScreeningOutcome] = []
        for document, _item, run in chunk:
            result = results[document.id]
            run.result = result.model_dump(mode="json")
            run.status = RunStatus.SUCCEEDED if error is None else RunStatus.FAILED
            run.error = None if error is None else f"{type(error).__name__}: {error}"[:2000]
            outcomes.append(ScreeningOutcome(run, result, False))
        self._session.flush()
        return outcomes

    def render_chunk(self, chunk):
        requested_ids = {document.id for document, _item, _run in chunk}
        try:
            response = self._provider.generate_structured(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(
                    {
                        "items": [
                            {
                                "document_version_id": str(document.id),
                                "title": item.title,
                            }
                            for document, item, _run in chunk
                        ]
                    },
                    ensure_ascii=False,
                ),
                output_model=TitleScreenBatch,
            )
            returned_ids = [item.document_version_id for item in response.items]
            if len(returned_ids) != len(set(returned_ids)):
                raise ValueError("Title screening response contains duplicate IDs")
            if set(returned_ids) != requested_ids:
                raise ValueError("Title screening response does not match requested IDs")
            results = {
                item.document_version_id: self._normalize_result(item)
                for item in response.items
            }
            error: Exception | None = None
        except Exception as exc:
            error = exc
            results = {
                document.id: TitleScreenResult(
                    document_version_id=document.id,
                    decision=TitleScreenDecision.NEEDS_BODY,
                    confidence=0,
                    reason="标题预筛失败，按高召回策略继续读取正文。",
                )
                for document, _item, _run in chunk
            }

        return results,error

    def _normalize_result(self, result: TitleScreenResult) -> TitleScreenResult:
        if result.decision == TitleScreenDecision.DROP:
            threshold = self._drop_confidence_floor
        else:
            threshold = self._confidence_floor
        if result.confidence >= threshold:
            return result
        return result.model_copy(
            update={
                "decision": TitleScreenDecision.NEEDS_BODY,
                "reason": f"低置信度（{result.confidence:.2f}），按高召回策略读取正文：{result.reason}",
            }
        )

    def _idempotency_key(
        self, document: DocumentVersion, item: SourceItem
    ) -> str:
        return (
            f"{AnalysisStage.ARTICLE_TITLE_SCREENING}:{document.id}:"
            f"{_title_signature(item.title)}:"
            f"{self._provider.metadata.config_version}:{self._prompt_version}"
        )


def _title_signature(title: str) -> str:
    normalized = " ".join(title.split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
