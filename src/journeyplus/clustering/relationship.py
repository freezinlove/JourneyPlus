from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import (
    AnalysisStage,
    EventHint,
    RelationshipResult,
    RelationshipType,
    RunStatus,
)
from journeyplus.models import AnalysisRun, DocumentVersion, StatusEvent


RELATIONSHIP_PROMPT_VERSION = "event-relationship-v1"
RELATIONSHIP_SCHEMA_VERSION = "1"

SYSTEM_PROMPT = """判断一个新的会籍获取机会提示与候选现实事件的关系。只可返回：SAME_EVENT（同一活动）、UPDATE_OF（同一活动的新规则/日期/资格）、DIFFERENT_EVENT（不同活动）或 UNCERTAIN。品牌相同并不自动代表同一活动；无法确信时返回 UNCERTAIN。SAME_EVENT、UPDATE_OF 或指向某候选的 UNCERTAIN 必须填写该候选 event ID。只输出符合 JSON Schema 的 JSON。"""


@dataclass(frozen=True, slots=True)
class RelationshipAnalysis:
    run: AnalysisRun | None
    result: RelationshipResult
    reused: bool


class EventRelationshipAnalyzer:
    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        prompt_version: str = RELATIONSHIP_PROMPT_VERSION,
    ) -> None:
        self._session = session
        self._provider = provider
        self._prompt_version = prompt_version

    def analyze(
        self,
        *,
        document: DocumentVersion,
        hint: EventHint,
        hint_index: int,
        candidates: list[StatusEvent],
    ) -> RelationshipAnalysis:
        if not candidates:
            return RelationshipAnalysis(
                None,
                RelationshipResult(
                    relationship=RelationshipType.DIFFERENT_EVENT,
                    confidence=1,
                    reason="候选召回为空，创建独立事件。",
                ),
                False,
            )
        candidate_payload = [
            {
                "id": str(item.id),
                "program": item.program,
                "opportunity_type": item.opportunity_type,
                "target_status": item.target_status,
                "summary": item.summary,
            }
            for item in candidates
        ]
        input_fingerprint = hashlib.sha256(
            json.dumps(candidate_payload, sort_keys=True).encode()
        ).hexdigest()[:16]
        key = (
            f"{AnalysisStage.EVENT_RELATIONSHIP}:{document.id}:{hint_index}:"
            f"{input_fingerprint}:{self._provider.metadata.config_version}:"
            f"{self._prompt_version}"
        )
        existing = self._session.scalar(
            select(AnalysisRun).where(AnalysisRun.idempotency_key == key)
        )
        if existing and existing.result:
            return RelationshipAnalysis(
                existing, RelationshipResult.model_validate(existing.result), True
            )
        run = existing or AnalysisRun(
            idempotency_key=key,
            document_version_id=document.id,
            stage=AnalysisStage.EVENT_RELATIONSHIP,
            status=RunStatus.RUNNING,
            input_version=f"{document.id}:{hint_index}:{input_fingerprint}",
            provider=self._provider.metadata.provider,
            model=self._provider.metadata.model,
            model_config_version=self._provider.metadata.config_version,
            prompt_version=self._prompt_version,
            schema_version=RELATIONSHIP_SCHEMA_VERSION,
        )
        if existing is None:
            self._session.add(run)
        try:
            result = self._provider.generate_structured(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(
                    {
                        "new_hint": hint.model_dump(mode="json"),
                        "new_material": document.normalized_body,
                        "candidates": candidate_payload,
                    },
                    ensure_ascii=False,
                ),
                output_model=RelationshipResult,
            )
            valid_ids = {candidate.id for candidate in candidates}
            if result.candidate_event_id and result.candidate_event_id not in valid_ids:
                raise ValueError("Model selected an event outside the retrieved candidates")
            if result.relationship in {
                RelationshipType.SAME_EVENT,
                RelationshipType.UPDATE_OF,
            } and result.candidate_event_id is None:
                raise ValueError("Selected relationship requires a candidate_event_id")
            run.status = RunStatus.SUCCEEDED
            run.result = result.model_dump(mode="json")
            run.error = None
        except Exception as exc:
            result = RelationshipResult(
                relationship=RelationshipType.UNCERTAIN,
                confidence=0,
                reason="事件关系输出无效，等待人工复核。",
            )
            run.status = RunStatus.FAILED
            run.result = result.model_dump(mode="json")
            run.error = f"{type(exc).__name__}: {exc}"[:2000]
        self._session.flush()
        return RelationshipAnalysis(run, result, False)


def resolve_candidate(
    session: Session, candidate_event_id: UUID | None
) -> StatusEvent | None:
    return session.get(StatusEvent, candidate_event_id) if candidate_event_id else None
