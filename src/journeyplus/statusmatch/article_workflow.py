from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass
from html import unescape
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, sessionmaker

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import (
    AnalysisStage,
    RunStatus,
)
from journeyplus.jobs.runner import JobRunner
from journeyplus.models import (
    AnalysisRun,
    BriefRecord,
    DocumentVersion,
    FactSetRecord,
    JobRun,
    SourceItem,
    StatusEvent,
    StatusMatchArticleRoute,
    StatusMatchArticleSupplement,
    StatusMatchWatch,
)
from journeyplus.statusmatch.article_contracts import (
    StatusMatchArticleExtraction,
)
from journeyplus.statusmatch.articles import (
    TERMINAL_ROUTE_STATUSES,
    refresh_statusmatch_article_route_readiness,
    third_party_statusmatch_links,
)


ARTICLE_PROMPT_VERSION = "statusmatch-third-party-highlights-v9"
ARTICLE_SCHEMA_VERSION = "3"

SYSTEM_PROMPT = """你只处理一篇已经由程序中的精确 *.statusmatch.com 链接确定归属的
第三方文章。不要分类，不要判断关系，不要创建活动，也不要修改官网事实。输入中的
OFFICIAL_FACT_SET 和 OFFICIAL_BRIEF 是当前官网 HOME+FAQ 的完整权威整理。

只输出补充关注点 highlights；highlights 是简体中文字符串数组，不输出类型、理由、原文摘录、
内部编号或状态。逐条比较，不要因为文章后半部分转载了官网 FAQ 就把整篇判为无新增。

关注点可以是官方整理没有保存的明确实用细节，也可以是文章作者明确表达、对判断是否值得申请
有实际帮助的观察。作者观察必须清楚写成“文章作者认为/提醒”，不能冒充官网事实。换一种说法
重复官方资格、等级、费用、日期、入口或限制不算新增；广告、纯情绪评价、没有实际价值的猜测
和“以官网为准”等套话也不算。每条必须由 ARTICLE 正文直接支持，但要用中文重新概括，不要
逐句复制原文。品牌和等级名可以保留原文。若没有真正新增内容，highlights 必须为空数组。

筛选时优先保留会影响“是否值得申请/如何使用”的等级权益、真实使用场景、机会成本和项目局限；
若官方整理只说“有权益”或只给外链，而 ARTICLE 明确列出行李、值机、SkyPriority、休息室等
具体权益，这些仍属于未覆盖的关注点。仅有品牌历史且不影响申请判断的背景不要保留。
作者对计划成熟度的不确定必须保持“作者不确定”的语气，
不能升级成已验证缺陷。所有数字、时间单位和 may/can/usually/most/depending on 等范围、概率、
条件限定都必须在中文 text 中忠实保留；原文只写 days 时不得改成“工作日”，原文写“视银行而定”
时不得省略该条件。

最多保留 4 条最高价值关注点，不得为了凑满上限而增加低价值内容。优先等级权益、费用价值和
项目局限；普通行政细节只有会显著改变申请决策时才保留。每条只能忠实概括文章实际表达，不得
把不同段落拼成文章没有给出的额外结论；例如文章只说“系统即时可验证”时不得添加“无需等待
实体卡”。

会籍匹配表述只有在构成相对官方产物的新颖、实用关注点时才可按上述 highlights 规则处理；
不要输出候选映射、审核状态或图关系。只输出严格 JSON。"""


@dataclass(frozen=True, slots=True)
class StatusMatchArticleProcessingResult:
    route_id: str
    project_host: str
    article_title: str
    article_url: str
    event_id: str
    document_version_id: str
    fact_set_id: str
    brief_id: str
    supplement_id: str
    status: str
    highlight_count: int
    mapping_claim_count: int
    model_calls: int


@dataclass(frozen=True, slots=True)
class StatusMatchArticleProcessingSummary:
    selected: int = 0
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    model_calls: int = 0
    routes: tuple[StatusMatchArticleProcessingResult, ...] = ()
    errors: tuple[str, ...] = ()


def process_pending_statusmatch_articles(
    session_factory: sessionmaker[Session],
    provider: AIProvider,
    *,
    limit: int = 100,
    route_ids: list[UUID | str] | tuple[UUID | str, ...] | None = None,
    hosts: list[str] | tuple[str, ...] | None = None,
) -> StatusMatchArticleProcessingSummary:
    if limit < 1:
        raise ValueError("limit must be positive")
    counted = _CallCountingProvider(provider)
    with session_factory.begin() as session:
        refresh_statusmatch_article_route_readiness(session, hosts=hosts)
    with session_factory() as session:
        candidates = _pending_route_rows(
            session,
            counted,
            route_ids=route_ids,
            hosts=hosts,
        )[:limit]

    runner = JobRunner(session_factory, max_attempts=1)
    results: list[StatusMatchArticleProcessingResult] = []
    errors: list[str] = []
    skipped = 0
    for route_id, key in candidates:
        def operation(
            current_route_id: UUID = route_id,
        ) -> StatusMatchArticleProcessingResult:
            with session_factory.begin() as session:
                route = session.get(StatusMatchArticleRoute, current_route_id)
                if route is None:
                    raise LookupError("StatusMatch article route disappeared")
                return StatusMatchArticleWorkflow(session, counted).process(route)

        try:
            result, was_skipped = runner.execute(
                idempotency_key=key,
                job_type="statusmatch_article_highlights",
                operation=operation,
                serialize=asdict,
            )
            if was_skipped:
                skipped += 1
            elif result is not None:
                results.append(result)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"[:2000]
            errors.append(message)
            with session_factory.begin() as session:
                route = session.get(StatusMatchArticleRoute, route_id)
                if route is not None:
                    route.status = "FAILED"
                    route.last_error = message
    return StatusMatchArticleProcessingSummary(
        selected=len(candidates),
        attempted=len(candidates),
        succeeded=len(results),
        failed=len(errors),
        skipped=skipped,
        model_calls=counted.calls,
        routes=tuple(results),
        errors=tuple(errors),
    )


def pending_statusmatch_article_count(
    session: Session,
    provider: AIProvider,
    *,
    hosts: list[str] | tuple[str, ...] | None = None,
) -> int:
    statement = (
        select(func.count())
        .select_from(StatusMatchArticleRoute)
        .where(
            StatusMatchArticleRoute.event_id.is_(None),
            ~StatusMatchArticleRoute.status.in_(TERMINAL_ROUTE_STATUSES),
        )
    )
    if hosts is not None:
        normalized_hosts = {host.casefold().rstrip(".") for host in hosts}
        statement = statement.where(
            StatusMatchArticleRoute.project_host.in_(normalized_hosts)
        )
    unready = int(session.scalar(statement) or 0)
    return unready + len(
        _pending_route_rows(session, provider, route_ids=None, hosts=hosts)
    )


def statusmatch_article_job_key(
    route: StatusMatchArticleRoute,
    event: StatusEvent,
    provider: AIProvider,
) -> str:
    input_version = _input_version(route, event, provider)
    return f"statusmatch-article:{route.id}:{input_version}"


class StatusMatchArticleWorkflow:
    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        max_attempts: int = 2,
    ) -> None:
        self._session = session
        self._provider = provider
        self._max_attempts = max_attempts

    def process(
        self,
        route: StatusMatchArticleRoute,
    ) -> StatusMatchArticleProcessingResult:
        document, item, event, fact, brief = _ready_materials(self._session, route)
        if route.project_host not in {
            link.host for link in third_party_statusmatch_links(self._session, document)
        }:
            raise ValueError("Article no longer contains its persisted project link")
        input_version = _input_version(route, event, self._provider)
        existing = self._session.scalar(
            select(StatusMatchArticleSupplement).where(
                StatusMatchArticleSupplement.route_id == route.id,
                StatusMatchArticleSupplement.fact_set_id == fact.id,
                StatusMatchArticleSupplement.brief_id == brief.id,
                StatusMatchArticleSupplement.input_version == input_version,
            )
        )
        if existing is not None:
            route.status = existing.status
            route.last_error = None
            return _result(route, item, event, document, fact, brief, existing, 0)

        extraction, attempts, analysis = self._extract(
            route=route,
            document=document,
            item=item,
            event=event,
            fact=fact,
            brief=brief,
            input_version=input_version,
        )
        analysis.result = extraction.model_dump(mode="json")
        analysis.status = RunStatus.SUCCEEDED
        analysis.error = None
        status = "SUCCEEDED" if extraction.highlights else "NO_NOVEL_HIGHLIGHTS"
        supplement = StatusMatchArticleSupplement(
            route_id=route.id,
            event_id=event.id,
            article_document_version_id=document.id,
            fact_set_id=fact.id,
            brief_id=brief.id,
            analysis_run_id=analysis.id,
            input_version=input_version,
            status=status,
            highlights=extraction.highlights,
            # Kept empty for backward database compatibility. Linked articles are
            # highlights-only and never contribute membership graph claims.
            mapping_claims=[],
        )
        self._session.add(supplement)
        route.status = status
        route.last_error = None
        self._session.flush()
        return _result(
            route,
            item,
            event,
            document,
            fact,
            brief,
            supplement,
            attempts,
        )

    def _extract(
        self,
        *,
        route: StatusMatchArticleRoute,
        document: DocumentVersion,
        item: SourceItem,
        event: StatusEvent,
        fact: FactSetRecord,
        brief: BriefRecord,
        input_version: str,
    ) -> tuple[StatusMatchArticleExtraction, int, AnalysisRun]:
        key = (
            f"{AnalysisStage.STATUSMATCH_ARTICLE_HIGHLIGHTS}:{route.id}:"
            f"{input_version}"
        )
        run = self._session.scalar(
            select(AnalysisRun).where(AnalysisRun.idempotency_key == key)
        )
        if run is not None and run.result is not None:
            return StatusMatchArticleExtraction.model_validate(run.result), 0, run
        if run is None:
            run = AnalysisRun(
                idempotency_key=key,
                document_version_id=document.id,
                event_id=event.id,
                stage=AnalysisStage.STATUSMATCH_ARTICLE_HIGHLIGHTS,
                status=RunStatus.RUNNING,
                input_version=input_version,
                provider=self._provider.metadata.provider,
                model=self._provider.metadata.model,
                model_config_version=self._provider.metadata.config_version,
                prompt_version=ARTICLE_PROMPT_VERSION,
                schema_version=ARTICLE_SCHEMA_VERSION,
            )
            self._session.add(run)
            self._session.flush()
        else:
            run.status = RunStatus.RUNNING
            run.error = None

        request: dict[str, Any] = {
            "project_host": route.project_host,
            "ARTICLE": {
                "title": item.title,
                "source_url": item.canonical_url,
                "published_at": (
                    item.published_at.isoformat()
                    if item.published_at is not None
                    else None
                ),
                "body": document.normalized_body,
            },
            "OFFICIAL_FACT_SET": _compact_official_facts(fact.facts),
            "OFFICIAL_BRIEF": brief.content,
            "rules": {
                "maximum_highlights": 4,
                "highlights_must_be_chinese_paraphrases": True,
                "never_output_original_quotes": True,
                "omit_if_covered_by_either_official_input": True,
                "never_output_membership_mapping_claims": True,
            },
        }
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            payload = dict(request)
            if last_error is not None:
                payload["correction"] = {
                    "previous_attempt_rejected_for": _safe_error(last_error),
                    "required_action": (
                        "删除重复、空白或无依据内容；highlights 只能是最多 4 条中文"
                        "概括，不要输出原文摘录、类型、理由、内部编号、状态、候选"
                        "会籍映射或图关系。"
                    ),
                }
            try:
                extraction = self._provider.generate_structured(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(payload, ensure_ascii=False),
                    output_model=StatusMatchArticleExtraction,
                )
                _validate_extraction(extraction)
                return extraction, attempt, run
            except Exception as exc:
                last_error = exc
        run.status = RunStatus.FAILED
        run.error = _safe_error(last_error or RuntimeError("unknown extraction error"))
        self._session.flush()
        raise ValueError(
            f"StatusMatch article extraction failed after {self._max_attempts} "
            f"attempts: {run.error}"
        ) from last_error


def _pending_route_rows(
    session: Session,
    provider: AIProvider,
    *,
    route_ids: list[UUID | str] | tuple[UUID | str, ...] | None,
    hosts: list[str] | tuple[str, ...] | None,
) -> list[tuple[UUID, str]]:
    normalized_route_ids = (
        [UUID(str(value)) for value in route_ids]
        if route_ids is not None
        else None
    )
    if normalized_route_ids == []:
        return []
    newer = aliased(DocumentVersion)
    latest_document_id = (
        select(newer.id)
        .where(newer.source_item_id == DocumentVersion.source_item_id)
        .order_by(newer.created_at.desc(), newer.id.desc())
        .limit(1)
        .correlate(DocumentVersion)
        .scalar_subquery()
    )
    statement = (
        select(StatusMatchArticleRoute, StatusEvent)
        .join(StatusEvent, StatusEvent.id == StatusMatchArticleRoute.event_id)
        .join(
            DocumentVersion,
            DocumentVersion.id == StatusMatchArticleRoute.document_version_id,
        )
        .join(
            StatusMatchWatch,
            StatusMatchWatch.current_event_id == StatusEvent.id,
        )
        .where(
            ~StatusMatchArticleRoute.status.in_(TERMINAL_ROUTE_STATUSES),
            StatusEvent.archived_at.is_(None),
            StatusEvent.merged_into_id.is_(None),
            StatusEvent.current_fact_set_id.is_not(None),
            StatusEvent.current_brief_id.is_not(None),
            StatusMatchWatch.status == "ACTIVE",
            DocumentVersion.id == latest_document_id,
        )
        .order_by(StatusMatchArticleRoute.created_at, StatusMatchArticleRoute.id)
    )
    if normalized_route_ids is not None:
        statement = statement.where(StatusMatchArticleRoute.id.in_(normalized_route_ids))
    if hosts is not None:
        normalized_hosts = {host.casefold().rstrip(".") for host in hosts}
        statement = statement.where(
            StatusMatchArticleRoute.project_host.in_(normalized_hosts)
        )
    rows: list[tuple[UUID, str]] = []
    for route, event in session.execute(statement):
        key = statusmatch_article_job_key(route, event, provider)
        completed = session.scalar(
            select(JobRun.id).where(
                JobRun.idempotency_key == key,
                JobRun.status == RunStatus.SUCCEEDED,
            )
        )
        if completed is None:
            rows.append((route.id, key))
    return rows


def _ready_materials(
    session: Session,
    route: StatusMatchArticleRoute,
) -> tuple[DocumentVersion, SourceItem, StatusEvent, FactSetRecord, BriefRecord]:
    document = session.get(DocumentVersion, route.document_version_id)
    if document is None:
        raise LookupError("StatusMatch article document was not found")
    item = session.get(SourceItem, document.source_item_id)
    if item is None:
        raise LookupError("StatusMatch article source item was not found")
    event = session.get(StatusEvent, route.event_id) if route.event_id else None
    watch = session.scalar(
        select(StatusMatchWatch).where(
            StatusMatchWatch.host == route.project_host,
            StatusMatchWatch.current_event_id == route.event_id,
            StatusMatchWatch.status == "ACTIVE",
        )
    )
    if (
        event is None
        or watch is None
        or event.archived_at is not None
        or event.current_fact_set_id is None
        or event.current_brief_id is None
    ):
        raise ValueError("StatusMatch article route lacks current official output")
    fact = session.get(FactSetRecord, event.current_fact_set_id)
    brief = session.get(BriefRecord, event.current_brief_id)
    if fact is None or brief is None or brief.fact_set_id != fact.id:
        raise ValueError("StatusMatch current FactSet and Brief are inconsistent")
    return document, item, event, fact, brief


def _input_version(
    route: StatusMatchArticleRoute,
    event: StatusEvent,
    provider: AIProvider,
) -> str:
    payload = {
        "route": str(route.id),
        "document": str(route.document_version_id),
        "event": str(event.id),
        "fact_set": str(event.current_fact_set_id),
        "brief": str(event.current_brief_id),
        "provider": provider.metadata.config_version,
        "prompt": ARTICLE_PROMPT_VERSION,
        "schema": ARTICLE_SCHEMA_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]


def _validate_extraction(
    extraction: StatusMatchArticleExtraction,
) -> None:
    seen: set[str] = set()
    for index, highlight in enumerate(extraction.highlights):
        key = _comparison_text(highlight)
        if key in seen:
            raise ValueError(f"highlight {index} duplicates an earlier highlight")
        seen.add(key)


def _compact_official_facts(facts: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "schema_version": facts.get("schema_version"),
    }
    for key, value in facts.items():
        if key in {"schema_version", "event_id", "application_routes", "status_mappings"}:
            continue
        if isinstance(value, dict) and (
            "value" in value or "conflict" in value or "alternatives" in value
        ):
            compact[key] = {
                "value": value.get("value"),
                "conflict": bool(value.get("conflict")),
                "alternatives": value.get("alternatives") or [],
            }
    compact["application_routes"] = [
        {
            key: value
            for key, value in route.items()
            if key not in {"evidence"}
        }
        for route in facts.get("application_routes", [])
        if isinstance(route, dict)
    ]
    mappings = [
        mapping
        for mapping in facts.get("status_mappings", [])
        if isinstance(mapping, dict)
    ]
    compact["status_mapping_coverage"] = {
        "count": len(mappings),
        "claims": [
            {
                "source_program": mapping.get("source_program"),
                "source_tiers": mapping.get("source_tiers") or [],
                "target_tier": mapping.get("target_tier"),
                "availability": mapping.get("availability"),
                "conditions": mapping.get("conditions"),
            }
            for mapping in mappings
        ],
    }
    return compact


def _comparison_text(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", unescape(value)).casefold().split()
    )


def _result(
    route: StatusMatchArticleRoute,
    item: SourceItem,
    event: StatusEvent,
    document: DocumentVersion,
    fact: FactSetRecord,
    brief: BriefRecord,
    supplement: StatusMatchArticleSupplement,
    model_calls: int,
) -> StatusMatchArticleProcessingResult:
    return StatusMatchArticleProcessingResult(
        route_id=str(route.id),
        project_host=route.project_host,
        article_title=item.title,
        article_url=item.canonical_url,
        event_id=str(event.id),
        document_version_id=str(document.id),
        fact_set_id=str(fact.id),
        brief_id=str(brief.id),
        supplement_id=str(supplement.id),
        status=supplement.status,
        highlight_count=len(supplement.highlights),
        mapping_claim_count=0,
        model_calls=model_calls,
    )


def _safe_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:1000] or type(exc).__name__


class _CallCountingProvider:
    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider
        self.metadata = provider.metadata
        self.calls = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        return self._provider.generate_structured(**kwargs)
