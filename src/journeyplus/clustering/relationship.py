from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.clustering.retrieval import (
    _event_identity,
    matching_project_statusmatch_hosts,
)
from journeyplus.contracts import (
    AnalysisStage,
    EventHint,
    RelationshipResult,
    RelationshipType,
    RunStatus,
)
from journeyplus.lifecycle.service import (
    BEIJING_TZ,
    event_closed_for_automation,
    normalize_event_time,
    windows_non_overlapping,
)
from journeyplus.models import (
    AnalysisRun,
    DocumentVersion,
    EventEvidence,
    StatusEvent,
)


RELATIONSHIP_PROMPT_VERSION = "event-relationship-v7"
RELATIONSHIP_SCHEMA_VERSION = "2"

SYSTEM_PROMPT = """判断一个新的会籍获取机会提示与候选现实事件的关系。只可返回：SAME_EVENT（同一活动）、UPDATE_OF（同一活动的新规则/日期/资格）、DIFFERENT_EVENT（不同活动）或 UNCERTAIN。

项目全称、简称、中文名、英文名或 status match / paid status / fast track 等措辞不同，都不能单独证明活动不同。同一现实活动可以有多个目标等级、价格档、资格映射、地区或申请入口；如果行动链接、活动规则和材料表明它们属于同一活动，应返回 SAME_EVENT。同一命名项目下、获取机制相同的国家或群体入口，不得仅因适用国家、人群、目标档位或注册链接不同就拆分；这些差异只有在材料明确表明是独立活动、规则机制不同或申请窗口属于不同期次时才支持 DIFFERENT_EVENT。同品牌仍不自动代表同一活动：不同获取机制、明确独立的适用对象与规则、或不同时期的独立活动应返回 DIFFERENT_EVENT。申请窗口相同、重叠或一方缺失仍需结合完整材料判断；可靠且非重叠的新一期窗口在没有明确延期语义时必须返回 DIFFERENT_EVENT。延期只有在候选活动尚未超过原截止时间且未归档时才可返回 UPDATE_OF；过期或归档活动不会作为候选，过期后出现的延期、重开或新一期材料必须创建新事件。单独出现 OFFER UPDATED 或类似措辞不能证明 UPDATE_OF；只有同一活动确有规则、日期或资格变化时才返回 UPDATE_OF。

candidates.materials 是候选事件已关联的原始证据摘要，必须与 new_material 一起判断。候选召回只代表可能相关，绝不代表可以自动合并。输出布尔字段 deadline_extension：只有候选事件尚未超过原截止时间且未归档、new_material 明确表示同一活动的申请截止时间被延长、给出晚于候选当前截止时间的新值且关系为 UPDATE_OF 时才为 true；价格、资格、规则或其他日期更新必须为 false。无法确信时返回 UNCERTAIN。SAME_EVENT、UPDATE_OF 或指向某候选的 UNCERTAIN 必须填写该候选 event ID。只输出符合 JSON Schema 的 JSON。"""


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
        candidates = [
            candidate
            for candidate in candidates
            if not event_closed_for_automation(candidate)
        ]
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
        candidate_payload = [self._candidate_payload(item) for item in candidates]
        strong_candidate = _project_subdomain_candidate(
            document=document,
            hint=hint,
            candidates=candidates,
            candidate_payload=candidate_payload,
        )
        if strong_candidate is not None:
            return RelationshipAnalysis(
                None,
                RelationshipResult(
                    relationship=RelationshipType.SAME_EVENT,
                    confidence=1,
                    reason=(
                        "新材料与唯一候选共享同一项目专属 StatusMatch 子域，"
                        "且该子域与双方项目身份一致。"
                    ),
                    candidate_event_id=strong_candidate.id,
                ),
                False,
            )
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
            result = _apply_window_guard(hint, candidates, result)
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

    def _candidate_payload(self, event: StatusEvent) -> dict[str, object]:
        materials = list(
            self._session.execute(
                select(DocumentVersion.canonical_url, DocumentVersion.normalized_body)
                .join(
                    EventEvidence,
                    EventEvidence.document_version_id == DocumentVersion.id,
                )
                .where(EventEvidence.event_id == event.id)
                .order_by(EventEvidence.created_at.desc())
                .limit(3)
            )
        )
        material_text = "\n".join(
            normalized_body for _, normalized_body in materials
        )
        return {
            "id": str(event.id),
            "program": event.program,
            "target_status": event.target_status,
            "summary": event.summary,
            "search_text": event.search_text,
            "application_start_at": _time_text(event.application_start_at),
            "application_deadline_at": _time_text(event.application_deadline_at),
            "project_statusmatch_hosts": sorted(
                matching_project_statusmatch_hosts(
                    material_text, _event_identity(event)
                )
            ),
            "materials": [
                {
                    "source_url": source_url,
                    "text": normalized_body[:2500],
                }
                for source_url, normalized_body in materials
            ],
        }


def _project_subdomain_candidate(
    *,
    document: DocumentVersion,
    hint: EventHint,
    candidates: list[StatusEvent],
    candidate_payload: list[dict[str, object]],
) -> StatusEvent | None:
    if _explicit_new_period(document.normalized_body):
        return None
    new_identity = " ".join(
        value
        for value in (hint.program, hint.target_status, hint.summary)
        if value
    )
    new_hosts = matching_project_statusmatch_hosts(
        document.normalized_body, new_identity
    )
    if not new_hosts:
        return None

    matches: list[StatusEvent] = []
    for event, payload in zip(candidates, candidate_payload, strict=True):
        if _hint_window_non_overlapping(hint, event):
            continue
        project_hosts = payload.get("project_statusmatch_hosts")
        if not isinstance(project_hosts, list):
            continue
        candidate_hosts = {
            host for host in project_hosts if isinstance(host, str)
        }
        if new_hosts & candidate_hosts:
            matches.append(event)
    return matches[0] if len(matches) == 1 else None


_NEW_PERIOD_PATTERNS = (
    re.compile(r"\breturned\s+for\s+the\s+first\s+time\s+in\s+20\d{2}\b", re.I),
    re.compile(r"\b20\d{2}\s+(?:edition|iteration|version)\b", re.I),
    re.compile(r"(?:新一期|新一轮|新年度|首次回归|重新开放|重新推出)"),
)


def _explicit_new_period(material: str) -> bool:
    return any(pattern.search(material) for pattern in _NEW_PERIOD_PATTERNS)


def _apply_window_guard(
    hint: EventHint,
    candidates: list[StatusEvent],
    result: RelationshipResult,
) -> RelationshipResult:
    candidate = next(
        (
            item
            for item in candidates
            if item.id == result.candidate_event_id
        ),
        None,
    )
    if result.deadline_extension:
        if candidate is None or not _valid_deadline_extension(hint, candidate):
            raise ValueError(
                "deadline_extension requires a later evidenced deadline on the candidate"
            )
    if candidate is None or not _hint_window_non_overlapping(hint, candidate):
        return result
    if result.deadline_extension and _valid_deadline_extension(hint, candidate):
        return result
    return RelationshipResult(
        relationship=RelationshipType.DIFFERENT_EVENT,
        confidence=1,
        reason="申请窗口与候选活动可靠且不重叠，且没有有效的明确延期信号。",
    )


def _valid_deadline_extension(hint: EventHint, candidate: StatusEvent) -> bool:
    if event_closed_for_automation(candidate):
        return False
    new_start = normalize_event_time(hint.application_start, end_of_day=False)
    new_deadline = normalize_event_time(hint.application_deadline, end_of_day=True)
    current_deadline = candidate.application_deadline_at
    if new_deadline is None or current_deadline is None:
        return False
    if new_start is not None and new_start > _as_beijing(current_deadline):
        return False
    return new_deadline > _as_beijing(current_deadline)


def _hint_window_non_overlapping(hint: EventHint, event: StatusEvent) -> bool:
    return windows_non_overlapping(
        normalize_event_time(hint.application_start, end_of_day=False),
        normalize_event_time(hint.application_deadline, end_of_day=True),
        event.application_start_at,
        event.application_deadline_at,
    )


def _time_text(value) -> str | None:
    return _as_beijing(value).isoformat() if value is not None else None


def _as_beijing(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=BEIJING_TZ)
    return value.astimezone(BEIJING_TZ)


def resolve_candidate(
    session: Session, candidate_event_id: UUID | None
) -> StatusEvent | None:
    return session.get(StatusEvent, candidate_event_id) if candidate_event_id else None
