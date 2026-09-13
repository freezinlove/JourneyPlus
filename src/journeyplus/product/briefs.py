from __future__ import annotations

import re
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.contracts import Brief, FactSet, RoutePriceAvailability
from journeyplus.contracts import StatusMatchBrief, read_brief
from journeyplus.models import (
    ArticleAnalysisRecord,
    ArticleBriefRecord,
    ArticleOpportunityRecord,
    BriefRecord,
    FactSetRecord,
    SourceItem,
    StatusEvent,
)
from journeyplus.opportunity_shaping import (
    ChinaRegionAdvisory,
    china_region_advisory,
    effective_route_prices,
    parse_route_prices,
    with_legacy_opportunity_kind,
)
from journeyplus.product.contracts import BriefList, BriefListItem
from journeyplus.product.brief_data import action_links, fee_view, relation_context


_PUBLIC_FACT_LABELS = {
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


class ProductBriefService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(
        self,
        *,
        query: str | None = None,
        reachable_only: bool = False,
    ) -> BriefList:
        context = relation_context(self._session)
        items = [*self._official_items(context.paths), *self._article_items(context.paths)]
        items = [item.model_copy(update={"relationship": context.for_opportunity(item.opportunity_id)})
                 for item in items]
        if query:
            folded = query.casefold()
            items = [
                item
                for item in items
                if folded
                in f"{item.program} {item.target_status or ''} {item.title} {item.summary}".casefold()
            ]
        if reachable_only:
            items = [item for item in items if item.reachable]
        return BriefList(
            items=sorted(
                items,
                key=lambda item: (item.updated_at, str(item.opportunity_id)),
                reverse=True,
            )
        )

    def _official_items(self, paths: dict[UUID, list[str]]) -> list[BriefListItem]:
        result: list[BriefListItem] = []
        events = self._session.scalars(
            select(StatusEvent).where(
                StatusEvent.current_fact_set_id.is_not(None),
                StatusEvent.archived_at.is_(None),
            )
        )
        for event in events:
            fact_record = self._session.get(FactSetRecord, event.current_fact_set_id)
            if fact_record is None or fact_record.event_id != event.id:
                continue
            brief_record = (
                self._session.get(BriefRecord, event.current_brief_id)
                if event.current_brief_id is not None
                else None
            )
            # Facts can advance before their brief is ready. Match the detail
            # reader: honor a matching pointer, otherwise select this version only.
            if brief_record is None or brief_record.fact_set_id != fact_record.id:
                brief_record = self._session.scalar(
                    select(BriefRecord)
                    .where(BriefRecord.fact_set_id == fact_record.id)
                    .order_by(BriefRecord.version.desc())
                    .limit(1)
                )
            if brief_record is None:
                continue
            facts = FactSet.model_validate(
                with_legacy_opportunity_kind(
                    fact_record.facts,
                    summary=event.summary,
                    target_status=event.target_status,
                )
            )
            brief = read_brief(brief_record.content)
            result.append(
                _brief_item(
                    opportunity_id=fact_record.id,
                    source="STATUS_EVENT",
                    facts=facts,
                    program=event.program,
                    target_status=event.target_status,
                    lifecycle_status=event.lifecycle_status,
                    brief=brief,
                    published_at=event.created_at,
                    updated_at=brief_record.updated_at,
                    path=paths.get(fact_record.id),
                )
            )
        return result

    def _article_items(self, paths: dict[UUID, list[str]]) -> list[BriefListItem]:
        analyses = list(
            self._session.scalars(
                select(ArticleAnalysisRecord)
                .where(ArticleAnalysisRecord.status == "SUCCEEDED")
                .order_by(
                    ArticleAnalysisRecord.source_item_id,
                    ArticleAnalysisRecord.created_at.desc(),
                    ArticleAnalysisRecord.id.desc(),
                )
            )
        )
        latest = {}
        for analysis in analyses:
            latest.setdefault(analysis.source_item_id, analysis)
        result: list[BriefListItem] = []
        for analysis in latest.values():
            opportunities = self._session.scalars(
                select(ArticleOpportunityRecord).where(
                    ArticleOpportunityRecord.analysis_id == analysis.id,
                    ArticleOpportunityRecord.current_brief_id.is_not(None),
                )
            )
            for opportunity in opportunities:
                brief_record = self._session.get(
                    ArticleBriefRecord, opportunity.current_brief_id
                )
                if brief_record is None:
                    continue
                facts = FactSet.model_validate(
                    with_legacy_opportunity_kind(
                        opportunity.facts,
                        summary=opportunity.summary,
                        target_status=opportunity.target_status,
                    )
                )
                brief = read_brief(brief_record.content)
                source_item = self._session.get(SourceItem, analysis.source_item_id)
                result.append(
                    _brief_item(
                        opportunity_id=opportunity.id,
                        source="ORDINARY_ARTICLE",
                        facts=facts,
                        program=opportunity.program,
                        target_status=opportunity.target_status,
                        lifecycle_status=opportunity.lifecycle_status,
                        brief=brief,
                        published_at=(
                            source_item.published_at
                            if source_item is not None
                            else opportunity.created_at
                        ),
                        updated_at=brief_record.updated_at,
                        path=paths.get(opportunity.id),
                    )
                )
        return result


def _brief_item(
    *,
    opportunity_id,
    source: str,
    facts: FactSet,
    program: str,
    target_status: str | None,
    lifecycle_status: str,
    brief: Brief | StatusMatchBrief,
    published_at,
    updated_at,
    path: list[str] | None,
) -> BriefListItem:
    return BriefListItem(
        opportunity_id=opportunity_id,
        source=source,
        opportunity_kind=facts.opportunity_kind,
        program=program,
        target_status=target_status,
        lifecycle_status=lifecycle_status,
        title=_public_brief_text(brief.title),
        summary=_public_brief_text(brief.summary),
        eligibility=facts.eligibility.value,
        challenge_requirements=facts.challenge_requirements.value,
        deadline=facts.deadline.value,
        price_summaries=_price_summaries(facts),
        china_advisories=_china_advisories(facts),
        key_points=[_public_brief_text(item.text) for item in getattr(brief, "key_points", [])],
        caveats=[_public_brief_text(item.text) for item in getattr(brief, "caveats", [])],
        source_links=[str(item) for item in brief.source_links],
        published_at=published_at,
        updated_at=updated_at,
        path=path,
        reachable=path is not None,
        fee=fee_view(facts),
        action_links=action_links(facts),
    )


def _price_summaries(facts: FactSet) -> list[str]:
    if facts.application_routes:
        scoped_prices = [
            (route.scope, price)
            for route in facts.application_routes
            for price in effective_route_prices(
                route,
                common_cost=facts.cost.value,
                common_evidence=facts.cost.evidence,
            )
        ]
    else:
        scoped_prices = [
            ("默认申请路线", price)
            for price in (
                parse_route_prices(facts.cost.value, evidence=facts.cost.evidence)
                if facts.cost.value
                else []
            )
        ]
    summaries: list[str] = []
    for scope, price in scoped_prices:
        tier = f" · {price.target_tier}" if price.target_tier else ""
        if price.availability == RoutePriceAvailability.UNAVAILABLE:
            rendered = "不可用"
        elif price.amount is not None and price.currency is not None:
            amount = f"{price.currency} {_decimal_text(price.amount)}"
            rendered = (
                f"条件另付 {amount}"
                if price.availability == RoutePriceAvailability.CONDITIONAL
                else amount
            )
        else:
            rendered = price.availability.value
        summaries.append(f"{scope}{tier}: {rendered}")
    if not summaries and facts.cost.value:
        if "金额未公布" in facts.cost.value and "收费" in facts.cost.value:
            summaries.append("默认申请路线: 收费，金额未公布")
        elif facts.cost.value.strip() == "免费":
            summaries.append("默认申请路线: 免费")
    return list(dict.fromkeys(summaries))


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _public_brief_text(value: str) -> str:
    for internal, label in _PUBLIC_FACT_LABELS.items():
        value = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(internal)}(?![A-Za-z0-9_])",
            label,
            value,
        )
    return value


def _china_advisories(facts: FactSet) -> list[ChinaRegionAdvisory]:
    regions = (
        [route.region or facts.region.value for route in facts.application_routes]
        if facts.application_routes
        else [facts.region.value]
    )
    return list(dict.fromkeys(china_region_advisory(region) for region in regions))
