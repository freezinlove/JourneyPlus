from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import AnalysisStage, Brief, FactSet, RunStatus
from journeyplus.models import AnalysisRun, BriefRecord, FactSetRecord, StatusEvent


BRIEF_PROMPT_VERSION = "chinese-brief-v9"
BRIEF_SCHEMA_VERSION = "1"

SYSTEM_PROMPT = """你是中文旅行会籍机会编辑。只能读取输入的版本化 FactSet，用自己的中文重组核心信息，输出短标题、短摘要、要点、限制/不确定性和来源链接。标题最多引用 3 个最核心的 fact_keys；其余事实仍可在摘要、要点或限制中引用。标题、摘要、每个要点和每项限制都要用 fact_keys 声明依据；unknown_fact_keys 中的字段必须完全省略，不得出现在任何 fact_keys 中，也不得据此写出“符合条件的会员”等暗示存在具体资格的措辞。不得输出“具体要求以活动页面为准”“请查看官网”“条款和费用适用”等没有独立信息价值的通用兜底文字；必须使用 FactSet 中已有的具体资格、映射、价格、地区、有效期、入口或限制，缺失时直接省略。source_links 只能逐项复制 allowed_source_links 中的公开证据来源；Gmail 邮件不是事实材料或引用对象。action_link 是申请入口，可以在有事实依据的行动要点中说明，但绝不能放入 source_links。application_routes 是同一活动下分别有证据的申请路径，应按各路径的资格、地区、价格和入口准确说明，不得把路径差异写成冲突。status_mappings 是完整的原项目/原等级到目标等级映射；引用它时必须列出至少一个具体“原会籍 → 目标会籍”对应关系，禁止用“完整映射见页面”“覆盖多家航司”等概括性文案替代具体事实。文案中必须使用“申请路径”“会籍对应关系”等中文名称，不得直接输出 application_routes、status_mappings 等内部字段名。字段、路径或映射明确标记的冲突必须继续生成简报并写入不确定性，展示双方候选信息，不可擅自选择；NEEDS_REVIEW 只是后台审核状态，不是停止生成简报的条件。不得添加 FactSet 没有的日期、费用、资格、地域或结论，不得复制长段原文。只输出符合 JSON Schema 的 JSON。"""

_UNKNOWN_ABSENCE_PATTERNS = {
    "eligibility": re.compile(
        r"(?:资格|申请条件|适用对象|谁可申请).{0,60}(?:未明确|未说明|未知|未提供|没有给出|暂无)"
    ),
    "target_status": re.compile(
        r"(?:目标等级|会籍等级|级别).{0,60}(?:未明确|未说明|未知|未提供|没有给出|暂无)"
    ),
    "cost": re.compile(
        r"(?:费用|价格|收费).{0,60}(?:未明确|未说明|未知|未提供|没有给出|暂无)"
    ),
    "challenge_requirements": re.compile(
        r"(?:挑战要求|任务要求).{0,60}(?:未明确|未说明|未知|未提供|没有给出|暂无)"
    ),
    "region": re.compile(
        r"(?:地区|地域|国家范围).{0,60}(?:未明确|未说明|未知|未提供|没有给出|暂无)"
    ),
    "application_start": re.compile(
        r"(?:开始日期|开放日期).{0,60}(?:未明确|未说明|未知|未提供|没有给出|暂无)"
    ),
    "deadline": re.compile(
        r"(?:截止日期|截止时间).{0,60}(?:未明确|未说明|未知|未提供|没有给出|暂无)"
    ),
    "status_validity": re.compile(
        r"(?:有效期|有效时间).{0,60}(?:未明确|未说明|未知|未提供|没有给出|暂无)"
    ),
    "action_link": re.compile(
        r"(?:申请入口|申请链接).{0,60}(?:未明确|未说明|未知|未提供|没有给出|暂无)"
    ),
}
_GENERIC_PAGE_REFERENCE_RULE_ID = "BRIEF_GENERIC_PAGE_REFERENCE"
_GENERIC_CAVEAT_CLAIM_RE = re.compile(
    r"(?:具体|详细)?(?P<claim_term>申请要求|要求|条款(?:和|及|与)(?:费用|条件)|"
    r"费用(?:和|及|与)条款)"
    r"(?P<context>.{0,80})"
    r"(?P<reference_term>活动页|页面|官网|查看|为准)"
)
_GENERIC_MAPPING_REFERENCE_RE = re.compile(
    r"(?:完整|具体)?映射(?:见|请查看|覆盖多家|包括.+等)|"
    r"覆盖多家(?:航司|航空公司)"
)
_GENERIC_TERMS_APPLY_RULE_ID = "BRIEF_GENERIC_TERMS_APPLY"
_GENERIC_TERMS_APPLY_RE = re.compile(
    r"(?:^|[，。；：!?！？\s])"
    r"(?P<claim_term>条款(?:(?:和|及|与)(?:费用|条件))?|"
    r"费用(?:(?:和|及|与)条款)?)"
    r"(?P<context>均|可能|仍然|另行)?"
    r"(?P<reference_term>适用)"
    r"(?=$|[。；!?！？\s])"
)
_REQUALIFICATION_FACT_RE = re.compile(
    r"(?:重新达标|重新取得|续级|续期|requalif(?:y|ication)|"
    r"retain\s+the\s+benefits?.{0,80}beyond)",
    re.IGNORECASE,
)
_GROUNDING_EXCERPT_LIMIT = 160
_INTERNAL_FACT_LABELS = {
    "what_happened": "活动内容",
    "eligibility": "申请资格",
    "target_status": "目标会籍",
    "cost": "申请费用",
    "challenge_requirements": "挑战要求",
    "region": "适用地区",
    "application_start": "开始时间",
    "deadline": "截止时间",
    "status_validity": "会籍有效期",
    "action_link": "申请入口",
    "caveats": "限制条件",
    "application_routes": "申请路径",
    "status_mappings": "会籍对应关系",
}
_CONFLICT_FIELD_LABELS = {
    "what_happened": "活动内容",
    "eligibility": "申请资格",
    "target_status": "目标会籍",
    "cost": "申请费用",
    "challenge_requirements": "挑战要求",
    "region": "适用地区",
    "application_start": "开始时间",
    "deadline": "截止时间",
    "status_validity": "会籍有效期",
    "action_link": "申请入口",
    "caveats": "限制条件",
}


@dataclass(frozen=True, slots=True)
class BriefGeneration:
    run: AnalysisRun
    record: BriefRecord
    brief: Brief
    reused: bool


def _safe_error_message(exc: Exception) -> str:
    """Keep diagnostics useful without persisting model output or source text."""
    if isinstance(exc, ValidationError):
        errors = [
            {
                "type": item.get("type"),
                "location": [str(part) for part in item.get("loc", ())],
                "message": item.get("msg"),
            }
            for item in exc.errors(include_input=False, include_url=False)
        ]
        message = json.dumps(errors, ensure_ascii=False, separators=(",", ":"))
    else:
        message = " ".join(str(exc).split())
    return message[:500] or "No error message"


def _attempt_diagnostic(
    *, attempt: int, phase: str, exc: Exception
) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "phase": phase,
        "error_type": type(exc).__name__,
        "message": _safe_error_message(exc),
    }


def _bounded_claim_excerpt(
    text: str, *, match_start: int, match_end: int
) -> str:
    """Return bounded generated text around a validator match, never source text."""
    normalized = " ".join(text.split())
    if len(normalized) <= _GROUNDING_EXCERPT_LIMIT:
        return normalized
    context_budget = _GROUNDING_EXCERPT_LIMIT - (match_end - match_start)
    before = max(context_budget // 2, 0)
    start = max(match_start - before, 0)
    end = min(start + _GROUNDING_EXCERPT_LIMIT, len(normalized))
    start = max(end - _GROUNDING_EXCERPT_LIMIT, 0)
    excerpt = normalized[start:end]
    if start > 0:
        excerpt = f"…{excerpt[1:]}"
    if end < len(normalized):
        excerpt = f"{excerpt[:-1]}…"
    return excerpt


def _generic_page_reference_error(
    *,
    rule_id: str,
    claim_location: str,
    text: str,
    fact_keys: list[str],
    match: re.Match[str],
) -> ValueError:
    diagnostic = {
        "rule_id": rule_id,
        "claim_location": claim_location,
        "claim_term": match.group("claim_term"),
        "reference_term": match.group("reference_term"),
        "matched_text": re.sub(r"^(?:具体|详细)", "", match.group(0))[:_GROUNDING_EXCERPT_LIMIT],
        "claim_excerpt": _bounded_claim_excerpt(
            text, match_start=match.start(), match_end=match.end()
        ),
        "fact_keys": sorted(fact_keys),
    }
    return ValueError(
        "Brief uses a generic page-reference caveat instead of concrete facts | "
        + json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":"))
    )


def _fact_key_availability(fact_set: FactSet) -> tuple[list[str], list[str]]:
    fields = fact_set.fact_fields()
    known = [
        key
        for key, field in fields.items()
        if field.value is not None or field.conflict
    ]
    unknown = [
        key
        for key, field in fields.items()
        if field.value is None and not field.conflict
    ]
    if fact_set.application_routes:
        known.append("application_routes")
    else:
        unknown.append("application_routes")
    if fact_set.status_mappings:
        known.append("status_mappings")
    else:
        unknown.append("status_mappings")
    return sorted(known), sorted(unknown)


def _allowed_source_links(fact_set: FactSet) -> list[str]:
    fields = fact_set.fact_fields()
    return sorted(
        {
            str(evidence.source_url).rstrip("/")
            for evidence in [
                *(
                    evidence
                    for field in fields.values()
                    for evidence in field.evidence
                ),
                *(
                    evidence
                    for route in fact_set.application_routes
                    for evidence in route.evidence
                ),
                *(
                    evidence
                    for mapping in fact_set.status_mappings
                    for evidence in mapping.evidence
                ),
            ]
        }
    )


def _correction_action(exc: Exception) -> str:
    message = _safe_error_message(exc)
    if "title_fact_keys" in message and "at most 3" in message:
        return "标题只能保留最多 3 个最核心事实键；删除多余的 title_fact_keys，不要删除正文中的事实依据。"
    if "unsupported source link" in message:
        return (
            "source_links 只能逐项复制 allowed_source_links；不得把 action_link "
            "申请入口放入 source_links。"
        )
    if "unknown fact" in message:
        return (
            "移除所有未知事实引用；若原句只是要求查看品牌活动页，仅在 "
            "caveats 已知时改用 caveats，否则整句省略。"
        )
    if "describes an unknown fact field" in message:
        return "完全删除对未知字段及其“未明确/未提供”状态的描述。"
    if "generic page-reference caveat" in message:
        return "删除“以活动页为准”“请查看官网”或“条款和费用适用”等通用兜底句，只保留已有具体事实。"
    if "generic status-mapping reference" in message:
        return "列出至少一个 FactSet 中具体的原会籍等级 → 目标会籍等级对应关系；不得用‘完整映射见页面’或‘覆盖多家航司’替代。"
    if "post-match requalification caveat" in message:
        return "在限制/不确定性中明确写出 FactSet caveats 已记录的匹配到期后重新达标或续级要求。"
    return "严格按 known_fact_keys 与 allowed_source_links 修正上一版输出。"


def _normalize_brief_output(brief: Brief, fact_set: FactSet) -> Brief:
    """Keep editorial labels Chinese and make reviewable conflicts visible."""
    content = brief.model_dump(mode="json")
    for field_name in ("title", "summary"):
        content[field_name] = _replace_internal_fact_labels(content[field_name])
    for group_name in ("key_points", "caveats"):
        for point in content[group_name]:
            point["text"] = _replace_internal_fact_labels(point["text"])

    caveats = content["caveats"]
    covered = {key for point in caveats for key in point["fact_keys"]}
    missing: list[dict[str, Any]] = []
    for field_name, field in fact_set.fact_fields().items():
        if not field.conflict or field_name in covered:
            continue
        alternatives = "；".join(_bounded_fact_value(item) for item in field.alternatives)
        missing.append(
            {
                "text": (
                    f"{_CONFLICT_FIELD_LABELS[field_name]}存在来源冲突，"
                    f"后台已标记待复核：{alternatives}。"
                ),
                "fact_keys": [field_name],
            }
        )
    if (
        any(route.conflict for route in fact_set.application_routes)
        and "application_routes" not in covered
    ):
        details = "；".join(
            f"{route.scope}：{route.conflict_note}"
            for route in fact_set.application_routes
            if route.conflict and route.conflict_note
        )
        missing.append(
            {
                "text": f"申请路径存在来源冲突，后台已标记待复核：{_bounded_fact_value(details)}。",
                "fact_keys": ["application_routes"],
            }
        )
    if (
        any(mapping.conflict for mapping in fact_set.status_mappings)
        and "status_mappings" not in covered
    ):
        count = sum(mapping.conflict for mapping in fact_set.status_mappings)
        missing.append(
            {
                "text": f"会籍对应关系中有 {count} 项来源冲突，后台已标记待复核。",
                "fact_keys": ["status_mappings"],
            }
        )
    if len(missing) > 10:
        missing = missing[:10]
    retained_editorial_caveats = caveats[: max(0, 10 - len(missing))]
    content["caveats"] = [*retained_editorial_caveats, *missing]
    return Brief.model_validate(content)


def _replace_internal_fact_labels(value: str) -> str:
    for internal, label in _INTERNAL_FACT_LABELS.items():
        value = value.replace(internal, label)
    return value


def _bounded_fact_value(value: str, limit: int = 180) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 1] + "…"


class BriefGenerator:
    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        prompt_version: str = BRIEF_PROMPT_VERSION,
        max_attempts: int = 2,
    ) -> None:
        self._session = session
        self._provider = provider
        self._prompt_version = prompt_version
        self._max_attempts = max_attempts

    def generate(self, fact_record: FactSetRecord) -> BriefGeneration:
        fact_set = FactSet.model_validate(fact_record.facts)
        key = (
            f"{AnalysisStage.BRIEF_GENERATION}:{fact_record.id}:"
            f"{self._provider.metadata.config_version}:{self._prompt_version}"
        )
        existing = self._session.scalar(
            select(AnalysisRun).where(AnalysisRun.idempotency_key == key)
        )
        event = self._session.get(StatusEvent, fact_record.event_id)
        if event is None:
            raise LookupError("FactSet event was not found")
        if existing and existing.result:
            record = self._session.get(BriefRecord, event.current_brief_id)
            if record is not None and record.fact_set_id != fact_record.id:
                record = None
            if record is None:
                record = next(
                    (
                        item
                        for item in self._session.scalars(
                            select(BriefRecord)
                            .where(BriefRecord.fact_set_id == fact_record.id)
                            .order_by(BriefRecord.version.desc())
                        )
                        if item.content == existing.result
                    ),
                    None,
                )
            if record is not None:
                return BriefGeneration(
                    existing, record, Brief.model_validate(record.content), True
                )
        run = existing or AnalysisRun(
            idempotency_key=key,
            event_id=fact_record.event_id,
            stage=AnalysisStage.BRIEF_GENERATION,
            status=RunStatus.RUNNING,
            input_version=str(fact_record.id),
            provider=self._provider.metadata.provider,
            model=self._provider.metadata.model,
            model_config_version=self._provider.metadata.config_version,
            prompt_version=self._prompt_version,
            schema_version=BRIEF_SCHEMA_VERSION,
        )
        if existing is None:
            self._session.add(run)

        last_error: Exception | None = None
        attempt_diagnostics: list[dict[str, Any]] = []
        brief: Brief | None = None
        known_fact_keys, unknown_fact_keys = _fact_key_availability(fact_set)
        allowed_source_links = _allowed_source_links(fact_set)
        for attempt in range(1, self._max_attempts + 1):
            request_payload: dict[str, Any] = {
                "fact_set_id": str(fact_record.id),
                "fact_set": fact_record.facts,
                "known_fact_keys": known_fact_keys,
                "unknown_fact_keys": unknown_fact_keys,
                "allowed_source_links": allowed_source_links,
                "editorial_rules": [
                    "只能引用 known_fact_keys",
                    "unknown_fact_keys 必须从文案和 fact_keys 中省略",
                    "不得用查看活动页或通用条款提示代替已展开页面中的具体事实",
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
            except Exception as exc:
                last_error = exc
                attempt_diagnostics.append(
                    _attempt_diagnostic(
                        attempt=attempt,
                        phase="MODEL_GENERATION_OR_SCHEMA_VALIDATION",
                        exc=exc,
                    )
                )
                continue
            try:
                candidate = _normalize_brief_output(candidate, fact_set)
                self._validate(candidate, fact_record, fact_set)
                brief = candidate
                break
            except Exception as exc:
                last_error = exc
                attempt_diagnostics.append(
                    _attempt_diagnostic(
                        attempt=attempt,
                        phase="GROUNDING_VALIDATION",
                        exc=exc,
                    )
                )
        if brief is None:
            fields = fact_set.fact_fields()
            diagnostic_payload = {
                "stage": "BRIEF_GENERATION",
                "fact_set_id": str(fact_record.id),
                "event_id": str(fact_record.event_id),
                "attempt_limit": self._max_attempts,
                "known_fact_keys": known_fact_keys,
                "unknown_fact_keys": unknown_fact_keys,
                "allowed_source_link_count": len(
                    {
                        str(evidence.source_url).rstrip("/")
                        for evidence in [
                            *(
                                evidence
                                for field in fields.values()
                                for evidence in field.evidence
                            ),
                            *(
                                evidence
                                for route in fact_set.application_routes
                                for evidence in route.evidence
                            ),
                            *(
                                evidence
                                for mapping in fact_set.status_mappings
                                for evidence in mapping.evidence
                            ),
                        ]
                    }
                ),
                "attempts": attempt_diagnostics,
            }
            diagnostic_json = json.dumps(
                diagnostic_payload, ensure_ascii=False, separators=(",", ":")
            )
            run.status = RunStatus.FAILED
            run.error = diagnostic_json[:4000]
            self._session.flush()
            raise ValueError(
                f"Brief generation failed after {self._max_attempts} attempts: "
                f"{diagnostic_json}"
            ) from last_error

        run.status = RunStatus.SUCCEEDED
        run.result = brief.model_dump(mode="json")
        run.error = None
        version = (
            self._session.scalar(
                select(func.max(BriefRecord.version)).where(
                    BriefRecord.fact_set_id == fact_record.id
                )
            )
            or 0
        ) + 1
        record = BriefRecord(
            fact_set_id=fact_record.id,
            version=version,
            schema_version=brief.schema_version,
            content=brief.model_dump(mode="json"),
        )
        self._session.add(record)
        self._session.flush()
        event.current_brief_id = record.id
        self._session.flush()
        return BriefGeneration(run, record, brief, False)

    @staticmethod
    def _validate(brief: Brief, record: FactSetRecord, fact_set: FactSet) -> None:
        if brief.fact_set_id != record.id:
            raise ValueError("Brief fact_set_id does not match its input")
        fields = fact_set.fact_fields()
        route_key_available = bool(fact_set.application_routes)
        mapping_key_available = bool(fact_set.status_mappings)
        claim_groups = [
            ("title", brief.title, brief.title_fact_keys),
            ("summary", brief.summary, brief.summary_fact_keys),
            *(
                (f"key_points[{index}]", point.text, point.fact_keys)
                for index, point in enumerate(brief.key_points)
            ),
            *(
                (f"caveats[{index}]", point.text, point.fact_keys)
                for index, point in enumerate(brief.caveats)
            ),
        ]
        for claim_location, text, keys in claim_groups:
            for key in keys:
                if key == "application_routes":
                    if not route_key_available:
                        raise ValueError(
                            "Brief makes a claim from unknown fact: application_routes"
                        )
                    continue
                if key == "status_mappings":
                    if not mapping_key_available:
                        raise ValueError(
                            "Brief makes a claim from unknown fact: status_mappings"
                        )
                    continue
                if key not in fields:
                    raise ValueError(f"Brief references unknown fact key: {key}")
                field = fields[key]
                if field.value is None and not field.conflict:
                    raise ValueError(f"Brief makes a claim from unknown fact: {key}")
            if "status_mappings" in keys and _GENERIC_MAPPING_REFERENCE_RE.search(text):
                raise ValueError(
                    "Brief uses a generic status-mapping reference instead of concrete facts"
                )
            for key, pattern in _UNKNOWN_ABSENCE_PATTERNS.items():
                field = fields[key]
                if (
                    field.value is None
                    and not field.conflict
                    and pattern.search(text) is not None
                ):
                    raise ValueError(
                        f"Brief describes an unknown fact field: {key}"
                    )
            generic_match = _GENERIC_CAVEAT_CLAIM_RE.search(" ".join(text.split()))
            if generic_match is not None:
                raise _generic_page_reference_error(
                    rule_id=_GENERIC_PAGE_REFERENCE_RULE_ID,
                    claim_location=claim_location,
                    text=text,
                    fact_keys=keys,
                    match=generic_match,
                )
            generic_terms_match = _GENERIC_TERMS_APPLY_RE.search(
                " ".join(text.split())
            )
            if generic_terms_match is not None:
                raise _generic_page_reference_error(
                    rule_id=_GENERIC_TERMS_APPLY_RULE_ID,
                    claim_location=claim_location,
                    text=text,
                    fact_keys=keys,
                    match=generic_terms_match,
                )
        requalification = fact_set.caveats.value
        if (
            requalification is not None
            and _REQUALIFICATION_FACT_RE.search(requalification) is not None
            and not any("caveats" in keys for _, _, keys in claim_groups)
        ):
            raise ValueError("Brief omits an explicit post-match requalification caveat")
        allowed_links = {
            str(evidence.source_url).rstrip("/")
            for evidence in [
                *(
                    evidence
                    for field in fields.values()
                    for evidence in field.evidence
                ),
                *(
                    evidence
                    for route in fact_set.application_routes
                    for evidence in route.evidence
                ),
                *(
                    evidence
                    for mapping in fact_set.status_mappings
                    for evidence in mapping.evidence
                ),
            ]
        }
        if any(str(link).rstrip("/") not in allowed_links for link in brief.source_links):
            raise ValueError("Brief contains an unsupported source link")
        output_text = "\n".join(
            [
                brief.title,
                brief.summary,
                *(point.text for point in brief.key_points),
                *(point.text for point in brief.caveats),
            ]
        )
        fact_values = [
            *(field.value for field in fields.values() if field.value),
            *(
                value
                for route in fact_set.application_routes
                for value in (
                    route.scope,
                    route.eligibility,
                    route.region,
                    route.cost,
                    str(route.action_link) if route.action_link else None,
                    route.conflict_note,
                )
                if value
            ),
            *(
                value
                for mapping in fact_set.status_mappings
                for value in (
                    mapping.source_program,
                    *mapping.source_tiers,
                    mapping.target_tier,
                    mapping.conditions,
                    mapping.conflict_note,
                )
                if value
            ),
        ]
        for value in fact_values:
            if len(value) >= 160:
                for start in range(0, len(value) - 159):
                    if value[start : start + 160] in output_text:
                        raise ValueError("Brief repeats a long source-derived passage")
