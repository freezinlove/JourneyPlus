from __future__ import annotations

import hashlib
from html import unescape
import json
import logging
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import urlsplit, urlunsplit
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
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
    RoutePrice,
    RunStatus,
    StatusMapping,
)
from journeyplus.lifecycle.service import calculate_lifecycle, normalize_event_time
from journeyplus.cost_semantics import COST_EXTRACTION_RULES
from journeyplus.models import (
    AnalysisRun,
    ArticleAnalysisRecord,
    ArticleOpportunityRecord,
    DocumentVersion,
    SourceItem,
)


ARTICLE_INTERPRETATION_PROMPT_VERSION = "generic-article-interpretation-v12-merged-copy"
ARTICLE_INTERPRETATION_SCHEMA_VERSION = "10"

SYSTEM_PROMPT = """你是中文旅行会籍机会文章解析器。只处理输入这一篇文章，不搜索、不引用、不比较其他文章，也不判断文章间关系。

先做最终单标签判断：
- STATUS_OPPORTUNITY：文章报道至少一个可直接获得、升级、匹配、挑战、快速通道、付费直升、延期旅行忠诚度会籍，或精英定级进度促销的现实活动；
- NONE：只有普通积分、折扣、权益介绍、一般信用卡资讯、长期攻略或个人客服成功个案；
- UNCERTAIN：正文证据不足。

若是 STATUS_OPPORTUNITY，按现实活动输出 opportunities。同一活动的不同目标等级、价格档、资格映射不拆分；不同目标忠诚度项目且有各自独立行动入口才拆分。每个机会提取完整事实、各自适用的申请路径和会籍对应关系。不要跨机会串日期或条件。

每个 opportunity 必须输出 opportunity_kind，且只能为 STATUS_MATCH 或 OTHER。STATUS_MATCH
是广义产品范围：直接会籍匹配、会籍挑战、Fast Track、先获得临时会籍再完成任务延长，以及
通过公开合作方资格直接获得明确目标会籍。联名信用卡直接赠送会籍、双倍定级积分、精英夜、
MQD、Status Credit 或其他只增加定级进度但不直接取得明确目标等级的活动必须为 OTHER。
opportunity_kind 只控制个性化匹配，不影响本机会继续生成简报。

直接提取结构化字段，不输出逐字段 evidence、quote、locator；文档关联由程序维护。
不得使用常识补猜。文章没有明确说明的字段保持 null/空数组。
application_start/deadline 只能摘录当前活动申请窗口，不能用发布时间或会籍有效期代替。
action_link 只能使用正文中出现的链接。

status_mappings 只表示“已有某项目的明确会籍等级，可对应到目标会籍等级”的等级映射；积分转换来源、信用卡或普通会员资格属于申请路径，不是会籍映射。AVAILABLE/CONDITIONAL 映射必须列出至少一个 source_tier。

application_routes 只保存文章描述为当前可用的申请方法；previously、formerly、used to 等明确历史方法不能保存为当前路径。历史方法若放入 caveats，必须明确写成“此前曾使用、未确认当前仍可用”，绝不能改写成“如有问题仍可使用”的当前后备路径。普通限制条件属于 caveats，不要为了保存限制而把 route 标成 conflict。application_route 或 status_mapping 的 conflict 与 conflict_note 必须成对且只表示来源内部真实互斥：没有真实冲突时 conflict=false 且 conflict_note=null。

每条 application_route 的 prices 按目标等级保存当前路线费用。每个 price 必须保留支持该价格的
结构化金额与适用等级，raw_text 可省略；只有原文明确给出金额与币种时才填写 amount/currency。明确不可用的等级
写 availability=UNAVAILABLE 且 amount=null。基础申请费与可选升级费没有明确总价时不得相加猜测。
共同适用于所有路线的全局价格可以复制到各路线。

region 只记录申请人地域资格，不得把项目覆盖范围、酒店分布或商店所在地推断成申请地域。若正文只说项目在某区域运营而没限制申请人，region 保持 null。对“August 24–28, 2026”这类明确申请范围，application_start.value 分别写“August 24, 2026”，deadline.value 写“August 28, 2026”，无需复制原句。

每个机会必须同时输出中文 title 和 summary，直接用于最终简报。title 简洁说明真实机会类型，不把所有活动称为会籍匹配。summary 根据正文概述核心内容，材料充分时用三至五句话、约150至250字；不得凑字、虚构或逐行复述表格。不要输出数据库 ID、字段引用或另写简报。只输出 JSON。""" + "\n\n" + COST_EXTRACTION_RULES


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

    def interpret(self, document: DocumentVersion, *, rendered=None) -> ArticleInterpretationOutcome:
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
        if existing is None:
            existing = legacy_interpretation_run(self._session, document.id, self._provider)
        persisted = (
            self._session.scalar(
                select(ArticleAnalysisRecord).where(
                    ArticleAnalysisRecord.analysis_run_id == existing.id
                )
            )
            if existing is not None
            else None
        )
        if (
            existing is not None
            and existing.result
            and existing.status != RunStatus.FAILED
            and (persisted is None or persisted.status != "NEEDS_REVIEW")
        ):
            interpretation = ArticleInterpretation.model_validate(existing.result)
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
        else:
            run.status = RunStatus.RUNNING
            run.error = None
            run.result = None
        self._session.flush()

        interpretation, last_error = rendered if rendered is not None else self.render(document,item)
        if interpretation is None:
            interpretation = ArticleInterpretation(
                label=DocumentLabel.UNCERTAIN,
                confidence=0,
                reason="正文解析在有限重试后未通过结构或链接校验，等待人工复核。",
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

    def render(self, document, item):
        """Interpret detached source data without touching the database."""
        interpretation: ArticleInterpretation | None = None
        last_error: Exception | None = None
        invocation_id = str(uuid4())
        for _attempt in range(self._max_attempts):
            started = monotonic()
            stage = "model_call"
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
                stage = "fact_validation"
                if any(not op.title or not op.title.strip() for op in candidate.opportunities):
                    raise ValueError("Each opportunity must include its final brief title")
                candidate = _normalize_application_methods(document, candidate)
                self._validate_grounding(document, candidate)
                interpretation = candidate
                if _attempt:
                    _log_interpretation_attempt(document, item, invocation_id, _attempt + 1,
                        self._max_attempts, started, "recovered", stage)
                break
            except Exception as exc:
                last_error = exc
                _log_interpretation_attempt(document, item, invocation_id, _attempt + 1,
                    self._max_attempts, started,
                    "retrying" if _attempt + 1 < self._max_attempts else "exhausted", stage, exc)
        return interpretation, last_error

    def _materialize(
        self,
        document: DocumentVersion,
        item: SourceItem,
        run: AnalysisRun,
        interpretation: ArticleInterpretation,
    ) -> tuple[ArticleAnalysisRecord, tuple[ArticleOpportunityRecord, ...]]:
        analysis = self._session.scalar(
            select(ArticleAnalysisRecord).where(
                ArticleAnalysisRecord.analysis_run_id == run.id
            )
        )
        if analysis is None:
            analysis = ArticleAnalysisRecord(
                id=uuid5(NAMESPACE_URL, f"journeyplus:article-analysis:{run.id}"),
                document_version_id=document.id,
                source_item_id=item.id,
                analysis_run_id=run.id,
                input_version=str(document.id),
                content_signature=document.normalized_hash,
            )
            self._session.add(analysis)
        analysis.label = interpretation.label
        analysis.confidence = interpretation.confidence
        analysis.reason = interpretation.reason
        analysis.status = (
            "SUCCEEDED" if run.status == RunStatus.SUCCEEDED else "NEEDS_REVIEW"
        )
        self._session.flush()
        existing_opportunities = tuple(
            self._session.scalars(
                select(ArticleOpportunityRecord).where(
                    ArticleOpportunityRecord.analysis_id == analysis.id
                )
            )
        )
        if existing_opportunities:
            raise ValueError(
                "A review retry cannot replace already materialized opportunities"
            )
        records: list[ArticleOpportunityRecord] = []
        for extracted in interpretation.opportunities:
            from journeyplus.membership.identity import canonical_program, canonical_tier, normalize_facts
            extracted = extracted.model_copy(update={'program': canonical_program(extracted.program)})
            if extracted.target_status_name:
                extracted.target_status_name = canonical_tier(extracted.program, extracted.target_status_name)
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
            facts = normalize_facts(self._to_fact_set(document, record.id, extracted), extracted.program)
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
        for opportunity in interpretation.opportunities:
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
            opportunity_kind=extracted.opportunity_kind,
            **fields,
            application_routes=[
                ApplicationRoute(
                    scope=route.scope,
                    eligibility=route.eligibility,
                    region=route.region,
                    cost=route.cost,
                    prices=[
                        RoutePrice(
                            target_tier=price.target_tier,
                            amount=price.amount,
                            currency=price.currency,
                            availability=price.availability,
                            raw_text=price.raw_text,
                            evidence=evidence_refs(price.evidence),
                        )
                        for price in route.prices
                    ],
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


def _normalize_application_methods(document, interpretation):
    """Keep link/history normalization without requiring or matching quotations."""
    content = interpretation.model_dump(mode='json')
    historical = re.compile(r'\b(?:previously|formerly|used\s+to)\b', re.I)
    for opportunity in content['opportunities']:
        action = opportunity['action_link']
        if action.get('value') and action['value'] not in document.normalized_body:
            opportunity['action_link'] = {'value': None}
        routes = []
        for route in opportunity['application_routes']:
            if route.get('action_link') and route['action_link'] not in document.normalized_body:
                route['action_link'] = None
            # Historical metadata remains usable, but is never required.
            descriptions = [route.get(key) or '' for key in ('scope', 'eligibility', 'cost')]
            descriptions.extend(item['quote'] for item in route.get('evidence', []))
            if any(historical.search(text) for text in descriptions):
                continue
            if any(route.get(key) for key in ('eligibility', 'region', 'cost', 'action_link', 'prices')):
                routes.append(route)
        opportunity['application_routes'] = routes
        caveats = opportunity['caveats']
        if (caveats.get('value')
                and any(historical.search(item['quote']) for item in caveats.get('evidence', []))
                and any(marker in caveats['value'] for marker in ('如有问题', '仍可', '可发送', '可以发送'))):
            caveats['value'] = '文章仅说明邮件申请曾是过去使用的方式，未确认当前仍可用。'
    return ArticleInterpretation.model_validate(content)


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
            "必须为 true。未知事实用 null 或空对象。无需输出逐字段证据。"
            "不要复制整段或整表。"
        )
    return "修正字段结构和内部关系；缺失事实保持 null，不需要逐字段引文。申请链接使用正文中的实际链接。"


def legacy_interpretation_run(session, document_id, provider):
    """Reuse pre-merge results for the same document/config, never new model output."""
    return session.scalar(select(AnalysisRun).outerjoin(
        ArticleAnalysisRecord, ArticleAnalysisRecord.analysis_run_id == AnalysisRun.id,
    ).where(
        (ArticleAnalysisRecord.id.is_(None)) | (ArticleAnalysisRecord.status == "SUCCEEDED"),
        AnalysisRun.document_version_id == document_id,
        AnalysisRun.stage == AnalysisStage.ARTICLE_INTERPRETATION,
        AnalysisRun.prompt_version == "generic-article-interpretation-v11",
        AnalysisRun.model_config_version == provider.metadata.config_version,
        AnalysisRun.status == RunStatus.SUCCEEDED,
    ).order_by(AnalysisRun.created_at.desc()).limit(1))


def _log_interpretation_attempt(document, item, invocation_id, attempt, limit, started,
                                outcome, stage, error=None):
    """One-line diagnostics on stderr; never log body, response or provider URL."""
    url = urlsplit(str(document.canonical_url))
    article_url = urlunsplit((url.scheme, url.hostname or "", url.path, "", ""))
    event = {
        "event": "article_interpretation_attempt",
        "time": datetime.now(UTC).isoformat(),
        "invocation_id": invocation_id,
        "article_title": item.title[:300],
        "article_url": article_url,
        "attempt": attempt,
        "max_attempts": limit,
        "outcome": outcome,
        "stage": stage,
        "elapsed_ms": round((monotonic() - started) * 1000),
    }
    if error is not None:
        event["error_type"] = type(error).__name__
        if isinstance(error, ValidationError):
            event["stage"] = "schema_validation"
            event["reason"] = [
                {"type": e["type"], "location": [str(part) for part in e["loc"]],
                 "message": e["msg"][:500]}
                for e in error.errors(include_input=False, include_url=False, include_context=False)[:20]
            ]
            event["error_count"] = error.error_count()
        elif stage == "fact_validation":
            event["reason"] = _safe_error(error)
        elif isinstance(error, httpx.HTTPStatusError):
            event["reason"] = "Model API returned an unsuccessful HTTP status"
            event["http_status"] = error.response.status_code
        elif isinstance(error, (httpx.TimeoutException, TimeoutError)):
            event["reason"] = "Model call timed out"
        elif isinstance(error, json.JSONDecodeError):
            event["reason"] = "Model response is not valid JSON"
            event["json_line"] = error.lineno
            event["json_column"] = error.colno
        else:
            event["reason"] = "Model call failed; raw exception suppressed to avoid logging response or credentials"
    # WARNING remains visible in CLI's default logging configuration; recovered is
    # an explicit closure of a prior warning, not a fresh failure.
    logging.getLogger(__name__).warning(json.dumps(event, ensure_ascii=False))
