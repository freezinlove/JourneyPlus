from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.contracts import Brief, FactSet, RoutePriceAvailability
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
from journeyplus.product.opportunities import PersonalizedMatchService


class ProductBriefService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(
        self,
        *,
        query: str | None = None,
        reachable_only: bool = False,
    ) -> BriefList:
        reachable = {
            item.opportunity_id
            for item in PersonalizedMatchService(self._session).read().opportunities
            if item.path is not None
        }
        items = [*self._official_items(reachable), *self._article_items(reachable)]
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

    def _official_items(self, reachable: set) -> list[BriefListItem]:
        result: list[BriefListItem] = []
        events = self._session.scalars(
            select(StatusEvent).where(
                StatusEvent.current_fact_set_id.is_not(None),
                StatusEvent.current_brief_id.is_not(None),
            )
        )
        for event in events:
            fact_record = self._session.get(FactSetRecord, event.current_fact_set_id)
            brief_record = self._session.get(BriefRecord, event.current_brief_id)
            if fact_record is None or brief_record is None:
                continue
            facts = FactSet.model_validate(
                with_legacy_opportunity_kind(
                    fact_record.facts,
                    summary=event.summary,
                    target_status=event.target_status,
                )
            )
            brief = Brief.model_validate(brief_record.content)
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
                    reachable=fact_record.id in reachable,
                )
            )
        return result

    def _article_items(self, reachable: set) -> list[BriefListItem]:
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
                brief = Brief.model_validate(brief_record.content)
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
                        reachable=opportunity.id in reachable,
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
    brief: Brief,
    published_at,
    updated_at,
    reachable: bool,
) -> BriefListItem:
    return BriefListItem(
        opportunity_id=opportunity_id,
        source=source,
        opportunity_kind=facts.opportunity_kind,
        program=program,
        target_status=target_status,
        lifecycle_status=lifecycle_status,
        title=brief.title,
        summary=brief.summary,
        eligibility=facts.eligibility.value,
        challenge_requirements=facts.challenge_requirements.value,
        deadline=facts.deadline.value,
        price_summaries=_price_summaries(facts),
        china_advisories=_china_advisories(facts),
        key_points=[item.text for item in brief.key_points],
        caveats=[item.text for item in brief.caveats],
        source_links=[str(item) for item in brief.source_links],
        published_at=published_at,
        updated_at=updated_at,
        reachable=reachable,
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
                if facts.cost.value and facts.cost.evidence
                else []
            )
        ]
    summaries: list[str] = []
    for scope, price in scoped_prices:
        tier = f" · {price.target_tier}" if price.target_tier else ""
        if price.availability == RoutePriceAvailability.UNAVAILABLE:
            rendered = "不可用"
        elif price.amount is not None and price.currency is not None:
            rendered = f"{price.currency} {price.amount}"
        else:
            rendered = price.availability.value
        summaries.append(f"{scope}{tier}: {rendered}")
    return list(dict.fromkeys(summaries))


def _china_advisories(facts: FactSet) -> list[ChinaRegionAdvisory]:
    regions = (
        [route.region or facts.region.value for route in facts.application_routes]
        if facts.application_routes
        else [facts.region.value]
    )
    return list(dict.fromkeys(china_region_advisory(region) for region in regions))
