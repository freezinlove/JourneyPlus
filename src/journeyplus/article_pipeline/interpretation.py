from __future__ import annotations

import hashlib
from html import unescape
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.article_pipeline.contracts import (
    ArticleInterpretation,
    ArticleOpportunityExtraction,
    EvidenceQuote,
    ExtractedFactField,
)
from journeyplus.article_pipeline.visibility import calculate_mapping_visibility
from journeyplus.contracts import (
    AnalysisStage,
    ApplicationRoute,
    DocumentLabel,
    EvidenceRef,
    FactField,
    FactSet,
    RunStatus,
    StatusMapping,
)
from journeyplus.lifecycle.service import calculate_lifecycle, normalize_event_time
from journeyplus.models import (
    AnalysisRun,
    ArticleAnalysisRecord,
    ArticleOpportunityRecord,
    DocumentVersion,
    SourceItem,
)


ARTICLE_INTERPRETATION_PROMPT_VERSION = "generic-article-interpretation-v8"
ARTICLE_INTERPRETATION_SCHEMA_VERSION = "8"

SYSTEM_PROMPT = """你是中文旅行会籍机会文章解析器。只处理输入这一篇文章，不搜索、不引用、不比较其他文章，也不判断文章间关系。

先做最终单标签判断：
- STATUS_OPPORTUNITY：文章报道至少一个可直接获得、升级、匹配、挑战、快速通道、付费直升、延期旅行忠诚度会籍，或精英定级进度促销的现实活动；
- NONE：只有普通积分、折扣、权益介绍、一般信用卡资讯、长期攻略或个人客服成功个案；
- UNCERTAIN：正文证据不足。

若是 STATUS_OPPORTUNITY，按现实活动输出 opportunities。同一活动的不同目标等级、价格档、资格映射不拆分；不同目标忠诚度项目且有各自独立行动入口才拆分。每个机会提取完整事实、分别有证据的申请路径和会籍对应关系。不要跨机会串日期或条件。

每个非空事实都必须附带文章中的短原文 quote，quote 必须能在 normalized_body 中按空白归一化后逐字找到；不得使用常识补猜。文章没有明确说明的字段保持 null/空数组。application_start/deadline 只能摘录当前活动申请窗口，不能用发布时间或会籍有效期代替。action_link 只能使用正文中出现的链接。

status_mappings 只表示“已有某项目的明确会籍等级，可对应到目标会籍等级”的等级映射；积分转换来源、信用卡或普通会员资格属于申请路径，不是会籍映射。AVAILABLE/CONDITIONAL 映射必须列出至少一个 source_tier。

application_routes 只保存文章描述为当前可用的申请方法；previously、formerly、used to 等明确历史方法不能保存为当前路径。历史方法若放入 caveats，必须明确写成“此前曾使用、未确认当前仍可用”，绝不能改写成“如有问题仍可使用”的当前后备路径。普通限制条件属于 caveats，不要为了保存限制而把 route 标成 conflict。application_route 或 status_mapping 的 conflict 与 conflict_note 必须成对且只表示来源内部真实互斥：没有真实冲突时 conflict=false 且 conflict_note=null。

region 只记录申请人地域资格，不得把项目覆盖范围、酒店分布或商店所在地推断成申请地域。若正文只说项目在某区域运营而没限制申请人，region 保持 null。对“August 24–28, 2026”这类明确申请范围，application_start.value 分别写“August 24, 2026”，deadline.value 写“August 28, 2026”，两者 evidence.quote 都逐字复制包含完整范围的原句。只输出 JSON。"""


@dataclass(frozen=True, slots=True)
class ArticleInterpretationOutcome:
    run: AnalysisRun
    analysis: ArticleAnalysisRecord
    opportunities: tuple[ArticleOpportunityRecord, ...]
    interpretation: ArticleInterpretation
    reused: bool


class ArticleInterpreter:
    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        prompt_version: str = ARTICLE_INTERPRETATION_PROMPT_VERSION,
        max_attempts: int = 3,
    ) -> None:
        self._session = session
        self._provider = provider
        self._prompt_version = prompt_version
        self._max_attempts = max_attempts

    def interpret(self, document: DocumentVersion) -> ArticleInterpretationOutcome:
        item = self._session.get(SourceItem, document.source_item_id)
        if item is None:
            raise LookupError("Source item was not found")
        key = (
            f"{AnalysisStage.ARTICLE_INTERPRETATION}:{document.id}:"
            f"{self._provider.metadata.config_version}:{self._prompt_version}"
        )
        existing = self._session.scalar(
            select(AnalysisRun).where(AnalysisRun.idempotency_key == key)
        )
        if existing is not None and existing.result:
            interpretation = ArticleInterpretation.model_validate(existing.result)
            persisted = self._session.scalar(
                select(ArticleAnalysisRecord).where(
                    ArticleAnalysisRecord.analysis_run_id == existing.id
                )
            )
            if persisted is None:
                persisted, opportunities = self._materialize(
                    document, item, existing, interpretation
                )
            else:
                opportunities = tuple(
                    self._session.scalars(
                        select(ArticleOpportunityRecord)
                        .where(ArticleOpportunityRecord.analysis_id == persisted.id)
                        .order_by(ArticleOpportunityRecord.opportunity_index)
                    )
                )
            return ArticleInterpretationOutcome(
                existing, persisted, opportunities, interpretation, True
            )

        run = existing or AnalysisRun(
            idempotency_key=key,
            document_version_id=document.id,
            stage=AnalysisStage.ARTICLE_INTERPRETATION,
            status=RunStatus.RUNNING,
            input_version=str(document.id),
            provider=self._provider.metadata.provider,
            model=self._provider.metadata.model,
            model_config_version=self._provider.metadata.config_version,
            prompt_version=self._prompt_version,
            schema_version=ARTICLE_INTERPRETATION_SCHEMA_VERSION,
        )
        if existing is None:
            self._session.add(run)
        self._session.flush()

        interpretation: ArticleInterpretation | None = None
        last_error: Exception | None = None
        for _attempt in range(self._max_attempts):
            try:
                request_payload: dict[str, Any] = {
                    "title": item.title,
                    "canonical_url": document.canonical_url,
                    "published_at": (
                        item.published_at.isoformat()
                        if item.published_at is not None
                        else None
                    ),
                    "normalized_body": document.normalized_body,
                }
                if last_error is not None:
                    request_payload["correction"] = {
                        "previous_attempt_rejected_for": _safe_error(last_error),
                        "required_action": _correction_action(last_error),
                    }
                candidate = self._provider.generate_structured(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(request_payload, ensure_ascii=False),
                    output_model=ArticleInterpretation,
                )
                candidate, discarded_evidence = _remove_ungrounded_candidates(
                    document, candidate
                )
                if discarded_evidence:
                    candidate = candidate.model_copy(
                        update={
                            "reason": (
                                candidate.reason
                                + f"（确定性证据守卫移除了 {discarded_evidence} 条"
                                "无法逐字定位的候选证据及其无剩余依据的字段。）"
                            )[:1000]
                        }
                    )
                self._validate_grounding(document, candidate)
                interpretation = candidate
                break
            except Exception as exc:
                last_error = exc
        if interpretation is None:
            interpretation = ArticleInterpretation(
                label=DocumentLabel.UNCERTAIN,
                confidence=0,
                reason="正文解析在有限重试后未通过结构或证据校验，等待人工复核。",
            )
            run.status = RunStatus.FAILED
            run.error = _safe_error(last_error or RuntimeError("unknown error"))
        else:
            run.status = RunStatus.SUCCEEDED
            run.error = None
        run.result = interpretation.model_dump(mode="json")
        self._session.flush()
        analysis, opportunities = self._materialize(
            document, item, run, interpretation
        )
        return ArticleInterpretationOutcome(
            run, analysis, opportunities, interpretation, False
        )

    def _materialize(
        self,
        document: DocumentVersion,
        item: SourceItem,
        run: AnalysisRun,
        interpretation: ArticleInterpretation,
    ) -> tuple[ArticleAnalysisRecord, tuple[ArticleOpportunityRecord, ...]]:
        analysis = ArticleAnalysisRecord(
            id=uuid5(NAMESPACE_URL, f"journeyplus:article-analysis:{run.id}"),
            document_version_id=document.id,
            source_item_id=item.id,
            analysis_run_id=run.id,
            input_version=str(document.id),
            label=interpretation.label,
            confidence=interpretation.confidence,
            reason=interpretation.reason,
            status=(
                "SUCCEEDED"
                if run.status == RunStatus.SUCCEEDED
                else "NEEDS_REVIEW"
            ),
            content_signature=document.normalized_hash,
        )
        self._session.add(analysis)
        self._session.flush()
        records: list[ArticleOpportunityRecord] = []
        for extracted in interpretation.opportunities:
            application_start_at = (
                normalize_event_time(extracted.application_start.value, end_of_day=False)
                if not extracted.application_start.conflict
                else None
            )
            application_deadline_at = (
                normalize_event_time(extracted.deadline.value, end_of_day=True)
                if not extracted.deadline.conflict
                else None
            )
            visibility_until_at, visibility_policy = calculate_mapping_visibility(
                application_deadline_at=application_deadline_at,
                published_at=item.published_at,
                first_collected_at=item.created_at,
            )
            record = ArticleOpportunityRecord(
                id=uuid5(
                    NAMESPACE_URL,
                    f"journeyplus:article-opportunity:{analysis.id}:"
                    f"{extracted.opportunity_index}",
                ),
                analysis_id=analysis.id,
                opportunity_index=extracted.opportunity_index,
                program=extracted.program,
                target_status=(
                    (extracted.target_status_name or extracted.target_status.value)[:300]
                    if (extracted.target_status_name or extracted.target_status.value)
                    else None
                ),
                summary=extracted.summary,
                application_start_raw=extracted.application_start.value,
                application_deadline_raw=extracted.deadline.value,
                application_start_at=application_start_at,
                application_deadline_at=application_deadline_at,
                visibility_until_at=visibility_until_at,
                visibility_policy=visibility_policy,
                status="DRAFT",
                facts={},
                fact_signature="",
            )
            self._session.add(record)
            self._session.flush()
            facts = self._to_fact_set(document, record.id, extracted)
            facts_json = facts.model_dump(mode="json")
            record.facts = facts_json
            record.fact_signature = _json_signature(facts_json)
            record.lifecycle_status = calculate_lifecycle(
                record.application_start_at, record.application_deadline_at
            )
            record.action_links = _action_links(extracted)
            records.append(record)
        self._session.flush()
        return analysis, tuple(records)

    @staticmethod
    def _validate_grounding(
        document: DocumentVersion, interpretation: ArticleInterpretation
    ) -> None:
        normalized_body = _normalize_whitespace(document.normalized_body)
        readable_body = _readable_markdown_text(document.normalized_body)
        for opportunity_index, opportunity in enumerate(
            interpretation.opportunities
        ):
            evidence_groups: list[tuple[str, list[EvidenceQuote]]] = [
                *(
                    (f"fact.{field_name}", field.evidence)
                    for field_name, field in opportunity.fact_fields().items()
                ),
                *(
                    (f"application_routes[{index}]", route.evidence)
                    for index, route in enumerate(opportunity.application_routes)
                ),
                *(
                    (f"status_mappings[{index}]", mapping.evidence)
                    for index, mapping in enumerate(opportunity.status_mappings)
                ),
            ]
            for location, group in evidence_groups:
                for evidence_index, evidence in enumerate(group):
                    quote = _normalize_whitespace(evidence.quote)
                    if quote in normalized_body or quote in readable_body:
                        continue
                    raise ValueError(
                        "Evidence quote was not found in the article body at "
                        f"opportunities[{opportunity_index}].{location}"
                        f".evidence[{evidence_index}]"
                    )
            links = [
                *(str(route.action_link) for route in opportunity.application_routes if route.action_link),
                *(
                    [opportunity.action_link.value]
                    if opportunity.action_link.value is not None
                    else []
                ),
            ]
            for link in links:
                if link.rstrip("/") not in document.normalized_body and link not in document.normalized_body:
                    raise ValueError("Action link was not found in the article body")
        identities: set[tuple[str, str]] = set()
        owned_links: set[str] = set()
        for opportunity in interpretation.opportunities:
            identity = (
                _normalize_whitespace(opportunity.program).casefold(),
                _normalize_whitespace(opportunity.target_status_name or "").casefold(),
            )
            if identity in identities:
                raise ValueError("Multiple opportunities share the same local identity")
            identities.add(identity)
            links = {
                *(str(route.action_link).rstrip("/") for route in opportunity.application_routes if route.action_link),
                *(
                    [opportunity.action_link.value.rstrip("/")]
                    if opportunity.action_link.value
                    else []
                ),
            }
            if owned_links & links:
                raise ValueError("An action link is assigned to multiple opportunities")
            owned_links.update(links)

    @staticmethod
    def _to_fact_set(
        document: DocumentVersion,
        opportunity_id,
        extracted: ArticleOpportunityExtraction,
    ) -> FactSet:
        def evidence_refs(items: list[EvidenceQuote]) -> list[EvidenceRef]:
            return [
                EvidenceRef(
                    document_version_id=document.id,
                    source_url=document.canonical_url,
                    locator=item.quote,
                )
                for item in items
            ]

        def fact(field: ExtractedFactField) -> FactField:
            return FactField(
                value=field.value,
                evidence=evidence_refs(field.evidence),
                conflict=field.conflict,
                alternatives=field.alternatives,
            )

        fields: dict[str, Any] = {
            key: fact(value) for key, value in extracted.fact_fields().items()
        }
        return FactSet(
            event_id=opportunity_id,
            **fields,
            application_routes=[
                ApplicationRoute(
                    scope=route.scope,
                    eligibility=route.eligibility,
                    region=route.region,
                    cost=route.cost,
                    action_link=route.action_link,
                    evidence=evidence_refs(route.evidence),
                    conflict=route.conflict,
                    conflict_note=route.conflict_note,
                )
                for route in extracted.application_routes
            ],
            status_mappings=[
                StatusMapping(
                    source_program=mapping.source_program,
                    source_tiers=mapping.source_tiers,
                    target_tier=mapping.target_tier,
                    availability=mapping.availability,
                    conditions=mapping.conditions,
                    evidence=evidence_refs(mapping.evidence),
                    conflict=mapping.conflict,
                    conflict_note=mapping.conflict_note,
                )
                for mapping in extracted.status_mappings
            ],
        )


def _normalize_whitespace(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", unescape(value)).split())


def _readable_markdown_text(value: str) -> str:
    projected = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", value)
    projected = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", projected)
    projected = re.sub(r"<((?:https?://|mailto:)[^>]+)>", r"\1", projected)
    projected = re.sub(r"(?m)^\s{0,3}(?:#{1,6}|>|[-*+]\s)\s*", "", projected)
    projected = projected.replace("**", "").replace("__", "").replace("`", "")
    return _normalize_whitespace(projected)


def _json_signature(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _action_links(extracted: ArticleOpportunityExtraction) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    if extracted.action_link.value:
        links.append({"scope": "default", "url": extracted.action_link.value})
    links.extend(
        {"scope": route.scope, "url": str(route.action_link)}
        for route in extracted.application_routes
        if route.action_link is not None
    )
    unique: dict[tuple[str, str], dict[str, Any]] = {
        (item["scope"], item["url"]): item for item in links
    }
    return list(unique.values())


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        payload = [
            {
                "type": item.get("type"),
                "location": [str(part) for part in item.get("loc", ())],
                "message": item.get("msg"),
            }
            for item in exc.errors(include_input=False, include_url=False)
        ]
        return json.dumps(payload, ensure_ascii=False)[:2000]
    return f"{type(exc).__name__}: {' '.join(str(exc).split())}"[:2000]


def _correction_action(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return (
            "逐项修正 Schema 错误。AVAILABLE/CONDITIONAL status_mapping 必须有"
            "source_tiers；积分转换项目不是会籍等级映射，应从 status_mappings 删除。"
            "conflict=false 时 conflict_note 必须为 null，存在 conflict_note 时 conflict"
            "必须为 true。未知事实用 null 或空对象。所有 quote 仍须逐字复制。"
        )
    return (
        "所有 evidence.quote 必须从 normalized_body 可见文字中连续逐字复制；"
        "不要改写、拼接、纠正拼写或添加等号。无法找到精确短引文的事实必须"
        "改为 null/空证据，不能用概括短语充当引用。action_link 必须逐字来自正文。"
    )


def _remove_ungrounded_candidates(
    document: DocumentVersion,
    interpretation: ArticleInterpretation,
) -> tuple[ArticleInterpretation, int]:
    """Discard unsupported candidate material; never persist a fuzzy quote."""
    raw_body = _normalize_whitespace(document.normalized_body)
    readable_body = _readable_markdown_text(document.normalized_body)

    def grounded(quote: str) -> bool:
        normalized = _normalize_whitespace(quote)
        return normalized in raw_body or normalized in readable_body

    content = interpretation.model_dump(mode="json")
    discarded = 0
    field_names = (
        "what_happened",
        "eligibility",
        "target_status",
        "cost",
        "challenge_requirements",
        "region",
        "application_start",
        "deadline",
        "status_validity",
        "action_link",
        "caveats",
    )
    for opportunity in content["opportunities"]:
        for field_name in field_names:
            field = opportunity[field_name]
            evidence = field.get("evidence") or []
            retained = [item for item in evidence if grounded(item["quote"])]
            discarded += len(evidence) - len(retained)
            field["evidence"] = retained
            if field.get("value") is not None and not retained:
                opportunity[field_name] = {
                    "value": None,
                    "evidence": [],
                    "conflict": False,
                    "alternatives": [],
                }
            elif field.get("conflict") and not retained:
                opportunity[field_name] = {
                    "value": None,
                    "evidence": [],
                    "conflict": False,
                    "alternatives": [],
                }
        action_value = opportunity["action_link"].get("value")
        if action_value and action_value not in document.normalized_body:
            opportunity["action_link"] = {
                "value": None,
                "evidence": [],
                "conflict": False,
                "alternatives": [],
            }
            discarded += 1

        retained_routes = []
        for route in opportunity.get("application_routes") or []:
            evidence = route.get("evidence") or []
            route["evidence"] = [
                item for item in evidence if grounded(item["quote"])
            ]
            discarded += len(evidence) - len(route["evidence"])
            action_link = route.get("action_link")
            if action_link and action_link not in document.normalized_body:
                route["action_link"] = None
                discarded += 1
            if any(
                re.search(
                    r"\b(?:previously|formerly|used\s+to)\b",
                    item["quote"],
                    re.IGNORECASE,
                )
                for item in route["evidence"]
            ):
                discarded += len(route["evidence"])
                continue
            if route["evidence"] and any(
                route.get(key) is not None
                for key in ("eligibility", "region", "cost", "action_link")
            ):
                retained_routes.append(route)
        opportunity["application_routes"] = retained_routes

        caveats = opportunity["caveats"]
        if (
            caveats.get("value")
            and any(
                re.search(
                    r"\b(?:previously|formerly|used\s+to)\b",
                    item["quote"],
                    re.IGNORECASE,
                )
                for item in caveats.get("evidence") or []
            )
            and any(
                marker in caveats["value"]
                for marker in ("如有问题", "仍可", "可发送", "可以发送")
            )
        ):
            caveats["value"] = (
                "文章仅说明邮件申请曾是过去使用的方式，未确认当前仍可用。"
            )

        retained_mappings = []
        for mapping in opportunity.get("status_mappings") or []:
            evidence = mapping.get("evidence") or []
            mapping["evidence"] = [
                item for item in evidence if grounded(item["quote"])
            ]
            discarded += len(evidence) - len(mapping["evidence"])
            if mapping["evidence"]:
                retained_mappings.append(mapping)
        opportunity["status_mappings"] = retained_mappings
    return ArticleInterpretation.model_validate(content), discarded
