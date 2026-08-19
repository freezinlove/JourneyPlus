from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import AnalysisStage, FactSet, RunStatus
from journeyplus.models import (
    AnalysisRun,
    DocumentVersion,
    EventEvidence,
    FactSetRecord,
    StatusEvent,
)


FACT_PROMPT_VERSION = "fact-consolidation-v1"
FACT_SCHEMA_VERSION = "1"

SYSTEM_PROMPT = """你只整理一个会籍获取事件的证据事实。仅允许字段：发生事项、适用对象、可获得会籍、成本、挑战要求、地域、截止时间、会籍有效期、行动链接和限制。每个非空确定值必须绑定输入中真实存在的 document_version_id、对应 source_url 和简短证据定位。材料未说明的字段保持 value=null；来源冲突时设置 conflict=true、列出至少两个 alternatives 并绑定相关证据，不可自行裁决。不要提取其他主题，不要补猜。只输出符合 JSON Schema 的 JSON。"""


@dataclass(frozen=True, slots=True)
class FactConsolidation:
    run: AnalysisRun
    record: FactSetRecord
    fact_set: FactSet
    reused: bool


class FactConsolidator:
    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        prompt_version: str = FACT_PROMPT_VERSION,
        max_attempts: int = 2,
    ) -> None:
        self._session = session
        self._provider = provider
        self._prompt_version = prompt_version
        self._max_attempts = max_attempts

    def consolidate(self, event: StatusEvent) -> FactConsolidation:
        documents = self._documents(event)
        if not documents:
            raise ValueError("Cannot consolidate facts without event evidence")
        fingerprint = hashlib.sha256(
            "|".join(f"{item.id}:{item.raw_hash}" for item in documents).encode()
        ).hexdigest()[:20]
        key = (
            f"{AnalysisStage.FACT_CONSOLIDATION}:{event.id}:{fingerprint}:"
            f"{self._provider.metadata.config_version}:{self._prompt_version}"
        )
        existing = self._session.scalar(
            select(AnalysisRun).where(AnalysisRun.idempotency_key == key)
        )
        if existing and existing.result:
            record = self._session.get(FactSetRecord, event.current_fact_set_id)
            if record is None:
                record = next(
                    (
                        item
                        for item in self._session.scalars(
                            select(FactSetRecord)
                            .where(FactSetRecord.event_id == event.id)
                            .order_by(FactSetRecord.version.desc())
                        )
                        if item.facts == existing.result
                    ),
                    None,
                )
            if record is not None:
                return FactConsolidation(
                    existing, record, FactSet.model_validate(record.facts), True
                )

        run = existing or AnalysisRun(
            idempotency_key=key,
            event_id=event.id,
            stage=AnalysisStage.FACT_CONSOLIDATION,
            status=RunStatus.RUNNING,
            input_version=fingerprint,
            provider=self._provider.metadata.provider,
            model=self._provider.metadata.model,
            model_config_version=self._provider.metadata.config_version,
            prompt_version=self._prompt_version,
            schema_version=FACT_SCHEMA_VERSION,
        )
        if existing is None:
            self._session.add(run)
        payload = [
            {
                "document_version_id": str(document.id),
                "source_url": document.canonical_url,
                "body": document.normalized_body,
            }
            for document in documents
        ]
        allowed_ids = {document.id for document in documents}
        allowed_urls = {document.canonical_url for document in documents}
        last_error: Exception | None = None
        fact_set: FactSet | None = None
        for _attempt in range(self._max_attempts):
            try:
                candidate = self._provider.generate_structured(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(
                        {"event_id": str(event.id), "materials": payload},
                        ensure_ascii=False,
                    ),
                    output_model=FactSet,
                )
                self._validate_evidence(candidate, event, allowed_ids, allowed_urls)
                fact_set = candidate
                break
            except Exception as exc:
                last_error = exc
        if fact_set is None:
            run.status = RunStatus.FAILED
            run.error = f"{type(last_error).__name__}: {last_error}"[:2000]
            self._session.flush()
            raise ValueError("Fact consolidation failed evidence validation") from last_error

        run.status = RunStatus.SUCCEEDED
        run.result = fact_set.model_dump(mode="json")
        run.error = None
        version = (
            self._session.scalar(
                select(func.max(FactSetRecord.version)).where(
                    FactSetRecord.event_id == event.id
                )
            )
            or 0
        ) + 1
        has_conflicts = any(field.conflict for field in fact_set.fact_fields().values())
        record = FactSetRecord(
            event_id=event.id,
            version=version,
            schema_version=fact_set.schema_version,
            facts=fact_set.model_dump(mode="json"),
            has_conflicts=has_conflicts,
        )
        self._session.add(record)
        self._session.flush()
        event.current_fact_set_id = record.id
        if has_conflicts:
            event.status = "NEEDS_REVIEW"
        self._session.flush()
        return FactConsolidation(run, record, fact_set, False)

    def _documents(self, event: StatusEvent) -> list[DocumentVersion]:
        return list(
            self._session.scalars(
                select(DocumentVersion)
                .join(
                    EventEvidence,
                    EventEvidence.document_version_id == DocumentVersion.id,
                )
                .where(EventEvidence.event_id == event.id)
                .distinct()
                .order_by(DocumentVersion.fetched_at.asc())
            )
        )

    @staticmethod
    def _validate_evidence(
        fact_set: FactSet,
        event: StatusEvent,
        allowed_ids: set,
        allowed_urls: set[str],
    ) -> None:
        if fact_set.event_id != event.id:
            raise ValueError("FactSet event_id does not match the requested event")
        for field in fact_set.fact_fields().values():
            for evidence in field.evidence:
                if evidence.document_version_id not in allowed_ids:
                    raise ValueError("Fact cites a document outside the event")
                if str(evidence.source_url).rstrip("/") not in {
                    url.rstrip("/") for url in allowed_urls
                }:
                    raise ValueError("Fact cites a source URL outside the event")
