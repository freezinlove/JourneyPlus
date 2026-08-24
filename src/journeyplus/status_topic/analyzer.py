from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import (
    AnalysisStage,
    DocumentLabel,
    RelevanceResult,
    RunStatus,
)
from journeyplus.models import AnalysisRun, DocumentVersion, SourceItem


STATUS_RELEVANCE_PROMPT_VERSION = "status-document-classification-v12"
STATUS_RELEVANCE_SCHEMA_VERSION = "4"

SYSTEM_PROMPT = """你是会籍机会文档的单标签分类器。每份文档只能选择以下一个 label：
- STATUS_OPPORTUNITY：包含至少一个可直接获得、升级或延长航空、酒店或其他旅行忠诚度会籍的公开或群体公开机会，例如会籍匹配、会籍挑战、快速通道、会籍互通、付费直升、合作直接授予或延期。
- NONE：不包含上述直接会籍机会。
- UNCERTAIN：材料证据不足，无法可靠选择前两者，需要人工复核。

信用卡或购买可以是会籍机会的资格条件。限时奖励精英定级房晚、定级积分或类似会籍资格进度的促销也属于会籍机会。旅行预订、旅行顾问或旅行会员平台的持续会员层级也属于旅行忠诚度会籍：如果具体活动直接授予或升级到金卡等明确命名的精英等级，即使它不是航司、酒店或租车公司自己的计划，也应标为 STATUS_OPPORTUNITY。

普通奖励积分、买分/转分促销、积分票、积分房晚、房券、折扣券、普通信用卡资讯和单纯权益介绍本身不是会籍机会。必须区分“精英等级”与“普通付费会员产品”：名称中出现会员、会籍、Plus、Pass、Club 或 Card 并不自动代表精英等级；仅购买普通付费会员产品或订阅、且结果只是获得会员资格、券、折扣或权益包，没有直接授予明确精英等级或精英定级进度的促销，应标为 NONE。例如购买 Accor Plus 会员只赠餐饮券应标为 NONE。混合文章只为真正属于会籍机会的部分输出提示，不要因为同文出现会籍活动就把房券或折扣活动也提取出来。

按文档的主要目的判断。以长期教学、方法总结、系统性玩法指导为主要目的的攻略文档，即使提及可以获得会籍的路径，第一版也标为 NONE 且不输出 event_hint。个人通过客服邮箱申请成功的单一经历，如果只有第三方数据点、邮件地址或个人结果，没有官方公开活动页面，也没有可确认的群体资格、条款或活动公告，只能证明个案，不能证明公开或群体公开机会，应按攻略/经验标为 NONE。主要报道某个具体会籍活动的开始、变化、截止或当前实测结果的文档，才可标为 STATUS_OPPORTUNITY；具体活动报道可以包含申请步骤，但不能因此被误判为攻略。一篇时效性材料同时包含会籍机会和无关促销时，仍只标为 STATUS_OPPORTUNITY，并忽略无关部分。

STATUS_OPPORTUNITY 必须按现实活动输出最小 event_hint，而不是按措辞或档位拆分：同一活动的多个目标等级、价格档、资格映射只输出一个提示；同一合作活动中的双向会籍路径也只输出一个提示。不同目标忠诚度项目且具有各自独立官方行动入口时，必须输出不同提示，即使其中一个会籍可能被用作另一个活动的资格来源。例如 Malaysia Airlines Enrich 付费匹配与通过另一官方入口购买 Garuda Gold Privilege 是两个活动。只有彼此独立的现实活动才输出多个 event_hints。正文主体活动中顺带推荐的一句话替代链接、TIP 或延伸阅读不另建提示。

StatusMatch 邮件展开得到的项目活动首页和 `/faq` 是完整公开材料。它们可能很长，必须提炼现实活动粒度的关键信息，尤其是目标项目与等级、资格来源与等级映射、价格、地区、申请窗口、会籍有效期、申请入口和注意事项；不要因页面包含多条 FAQ 就拆成多个现实活动。region_hint 只需给出简洁区域摘要，不必逐一抄写很长的国家列表。

每个 event_hint 还可输出 application_start 和 application_deadline。只有材料明确给出当前活动的申请开始或截止文字时才原样摘录对应值；不得使用文章发布时间、会籍有效期或模型常识补猜。只有日期就保留该日期，明确给出时刻或时区时保留完整信息；系统后续统一按北京时间规范化。缺失值必须为 null，并且一篇多活动文档的时间不得串到其他 event_hint。

NONE 不得输出 event_hints。不要创建正式事件，不要输出机会机制类型字段，不要生成其他主题标签，不要补猜材料没有的信息。只输出符合给定 JSON Schema 的 JSON。"""


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
        discovery_only = self._mail_is_discovery_only(document)
        existing = self._session.scalar(
            select(AnalysisRun).where(AnalysisRun.idempotency_key == key)
        )
        if discovery_only:
            run = existing or AnalysisRun(
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
            )
            if existing is None:
                self._session.add(run)
            result = RelevanceResult(
                label=DocumentLabel.NONE,
                confidence=1,
                reason=self._discovery_only_reason(document),
                event_hints=[],
            )
            run.status = RunStatus.SUCCEEDED
            run.result = result.model_dump(mode="json")
            run.error = None
            self._session.flush()
            return RelevanceAnalysis(run, result, existing is not None)
        if existing and existing.result:
            result = self._finalize_result(
                document, RelevanceResult.model_validate(existing.result)
            )
            return RelevanceAnalysis(existing, result, True)

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
                reused_result = self._finalize_result(
                    document, RelevanceResult.model_validate(reusable.result)
                )
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
                    result=reused_result.model_dump(mode="json"),
                )
                self._session.add(run)
                self._session.flush()
                return RelevanceAnalysis(run, reused_result, True)

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
                    user_prompt=json.dumps(
                        {
                            "normalized_material": document.normalized_body,
                        },
                        ensure_ascii=False,
                    ),
                    output_model=RelevanceResult,
                )
                result = self._finalize_result(document, result)
                break
            except Exception as exc:
                last_error = exc
        if result is None:
            result = RelevanceResult(
                label=DocumentLabel.UNCERTAIN,
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

    @staticmethod
    def _finalize_result(
        document: DocumentVersion,
        result: RelevanceResult,
    ) -> RelevanceResult:
        if result.label != DocumentLabel.STATUS_OPPORTUNITY:
            return result
        if _is_email_only_anecdote(document):
            return RelevanceResult(
                label=DocumentLabel.NONE,
                confidence=max(result.confidence, 0.95),
                reason=(
                    "材料只有个人客服邮件成功经历和第三方数据点，没有官方活动"
                    "入口或可确认的群体条款；按公开性守卫视为个案攻略。"
                ),
                event_hints=[],
            )
        return result

    def _mail_is_discovery_only(self, document: DocumentVersion) -> bool:
        item = self._session.get(SourceItem, document.source_item_id)
        if item is None or item.source_id != "status_services_mail":
            return False
        metadata = item.raw_metadata or {}
        return (
            metadata.get("document_role") != "linked_statusmatch_page"
            or metadata.get("skip_semantic_processing") is True
        )

    def _discovery_only_reason(self, document: DocumentVersion) -> str:
        item = self._session.get(SourceItem, document.source_item_id)
        if item is not None and (item.raw_metadata or {}).get(
            "skip_semantic_processing"
        ) is True:
            return "页面已被确定性关闭规则处理并归档，不再创建新的活动语义记录。"
        return (
            "邮件仅用于发现项目活动链接；详细事实由已展开的活动首页和"
            "FAQ 独立处理。"
        )


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)
_PERSONAL_EMAIL_MARKERS = (
    "我给",
    "我发",
    "申请邮件",
    "i emailed",
    "i sent an email",
    "my account",
)
_THIRD_PARTY_DATA_MARKERS = (
    "statusmatcher.com",
    "第三方数据",
    "数据点",
    "data point",
)


def _is_email_only_anecdote(document: DocumentVersion) -> bool:
    body = document.normalized_body
    folded = body.casefold()
    if _EMAIL_RE.search(body) is None:
        return False
    if not any(marker in folded for marker in _PERSONAL_EMAIL_MARKERS):
        return False
    if not any(marker in folded for marker in _THIRD_PARTY_DATA_MARKERS):
        return False
    source_host = _normalized_host(document.canonical_url)
    external_hosts = {
        host
        for url in _URL_RE.findall(body)
        if (host := _normalized_host(url))
        and host != source_host
        and not host.endswith("statusmatcher.com")
    }
    return not external_hosts


def _normalized_host(value: str) -> str:
    host = (urlsplit(value.rstrip(".,;:!?")).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host
