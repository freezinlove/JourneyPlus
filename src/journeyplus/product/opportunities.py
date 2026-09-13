from __future__ import annotations

from journeyplus.lifecycle.visibility import effective_status, contributes

import re
from collections import deque
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.contracts import (
    ApplicationRoute,
    Brief,
    FactSet,
    OpportunityKind,
    RoutePrice,
    RoutePriceAvailability,
)
from journeyplus.lifecycle.service import BEIJING_TZ, as_beijing
from journeyplus.membership.contracts import (
    ReachableMembershipTreeEdge,
    ReachableMembershipTreeNode,
    UnifiedTreeNodeState,
)
from journeyplus.membership.normalization import normalize_tier, program_tier_key, target_program_aliases
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.contracts import StatusMatchBrief, read_brief
from journeyplus.models import (
    ArticleAnalysisRecord,
    ArticleBriefRecord,
    ArticleOpportunityRecord,
    BriefRecord,
    FactSetRecord,
    StatusEvent,
    StatusMatchArticleRoute,
    StatusMatchWatch,
)
from journeyplus.opportunity_shaping import (
    china_region_advisory,
    effective_route_prices,
    parse_route_prices,
    with_legacy_opportunity_kind,
)
from journeyplus.product.contracts import (
    MatchEdgeFee,
    MatchOpportunitySummary,
    OpportunityDetail,
    PersonalizedMatches,
    ProductApplicationRoute,
)
from journeyplus.product.holdings import StatusHoldingService


_FREE_COST = re.compile(
    r"^\s*(?:免费|无费用|无需付费|free(?:\s+of\s+charge)?)\s*[。.]?\s*$",
    re.IGNORECASE,
)


class PersonalizedMatchService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def read(
        self,
        *,
        now: datetime | None = None,
        technical_node_limit: int = 5000,
    ) -> PersonalizedMatches:
        current = as_beijing(now or datetime.now(BEIJING_TZ))
        holdings = StatusHoldingService(self._session).list()
        from journeyplus.memberships_validity import is_active_membership, membership_date
        active = [item for item in holdings if is_active_membership(item.valid_until, today=membership_date(current))]
        forest = UnifiedMembershipTreeService(self._session).reachable_forest(
            [item.node_id for item in active],
            technical_node_limit=technical_node_limit,
            now=current,
        )
        paths = _opportunity_paths(forest.roots)
        summaries: dict[UUID, MatchOpportunitySummary] = {}
        for opportunity_id, path in paths.items():
            summary = self._summary(opportunity_id, path=path, now=current)
            if summary is not None:
                summaries[opportunity_id] = summary
        for summary in self._standalone_article_matches(current):
            summaries.setdefault(summary.opportunity_id, summary)
        for summary in self._standalone_official_matches(now=current):
            summaries.setdefault(summary.opportunity_id, summary)
        return PersonalizedMatches(
            holdings=holdings,
            forest=forest,
            edge_fees=self._edge_fees(forest.roots),
            opportunities=sorted(
                summaries.values(),
                key=lambda item: (
                    item.program.casefold(),
                    (item.target_status or "").casefold(),
                    str(item.opportunity_id),
                ),
            ),
        )

    def _edge_fees(
        self, roots: list[ReachableMembershipTreeNode]
    ) -> list[MatchEdgeFee]:
        from journeyplus.knowledge.workflow_routes import matching_paid
        result: list[MatchEdgeFee] = []
        seen_edges: set[tuple[str, str]] = set()
        fee_cache: dict[tuple[UUID, str], list[str]] = {}

        def visit(node: ReachableMembershipTreeNode) -> None:
            for edge in node.children:
                edge_key = (edge.source_node_id, edge.target_node_id)
                if (
                    edge.child.state != UnifiedTreeNodeState.CYCLE
                    and edge_key not in seen_edges
                ):
                    seen_edges.add(edge_key)
                    target_tier_key = edge.target_node_id.rsplit("::", 1)[-1]
                    labels: list[str] = []
                    for opportunity_id in edge.opportunity_ids:
                        cache_key = (opportunity_id, target_tier_key)
                        if cache_key not in fee_cache:
                            facts = self._facts_for_opportunity(opportunity_id)
                            fee_cache[cache_key] = (
                                ['付费' if matching_paid(facts,target_tier_key,
                                    program_aliases=target_program_aliases(edge.child.node.program,
                                        (m.target_tier for m in facts.status_mappings))) else '免费']
                                if facts is not None
                                else []
                            )
                        labels.extend(fee_cache[cache_key])
                    labels = list(dict.fromkeys(labels))
                    if labels:
                        result.append(
                            MatchEdgeFee(
                                source_node_id=edge.source_node_id,
                                target_node_id=edge.target_node_id,
                                labels=labels,
                            )
                        )
                visit(edge.child)

        for root in roots:
            visit(root)
        return result

    def _facts_for_opportunity(self, opportunity_id: UUID) -> FactSet | None:
        fact_record = self._session.get(FactSetRecord, opportunity_id)
        if fact_record is not None:
            event = self._session.get(StatusEvent, fact_record.event_id)
            if event is None:
                return None
            return _validated_facts(
                fact_record.facts,
                summary=event.summary,
                target_status=event.target_status,
                managed_statusmatch=_is_managed_event(self._session, event.id),
            )
        article = self._session.get(ArticleOpportunityRecord, opportunity_id)
        if article is None:
            return None
        return _validated_facts(
            article.facts,
            summary=article.summary,
            target_status=article.target_status,
        )

    def detail(
        self,
        opportunity_id: UUID | str,
        *,
        include_current_path: bool = True,
    ) -> OpportunityDetail:
        resolved_id = UUID(str(opportunity_id))
        fact_record = self._session.get(FactSetRecord, resolved_id)
        if fact_record is not None:
            detail = self._official_detail(fact_record)
        else:
            article = self._session.get(ArticleOpportunityRecord, resolved_id)
            if article is None:
                raise LookupError(f"Opportunity {opportunity_id} was not found")
            detail = self._article_detail(article)
        if not include_current_path:
            return detail
        from journeyplus.product.brief_data import relation_context
        relation = relation_context(self._session).for_opportunity(resolved_id)
        return detail.model_copy(update={"path": relation.path, "relationship": relation})

    def _current_path(self, opportunity_id: UUID) -> list[str] | None:
        holdings = StatusHoldingService(self._session).list()
        forest = UnifiedMembershipTreeService(self._session).reachable_forest(
            [item.node_id for item in holdings]
        )
        return _opportunity_paths(forest.roots).get(opportunity_id)

    def _summary(
        self, opportunity_id: UUID, *, path: list[str] | None, now=None
    ) -> MatchOpportunitySummary | None:
        fact_record = self._session.get(FactSetRecord, opportunity_id)
        if fact_record is not None:
            event = self._session.get(StatusEvent, fact_record.event_id)
            if event is None:
                return None
            facts = _validated_facts(
                fact_record.facts,
                summary=event.summary,
                target_status=event.target_status,
                managed_statusmatch=_is_managed_event(self._session, event.id),
            )
            if facts.opportunity_kind != OpportunityKind.STATUS_MATCH:
                return None
            return MatchOpportunitySummary(
                opportunity_id=fact_record.id,
                source="STATUSMATCH_OFFICIAL",
                opportunity_kind=facts.opportunity_kind,
                program=event.program,
                target_status=event.target_status,
                summary=event.summary,
                lifecycle_status=effective_status(event, now=now),
                path=path,
                deadline=facts.deadline.value,
                conflict=_has_conflict(facts),
            )
        article = self._session.get(ArticleOpportunityRecord, opportunity_id)
        if article is None:
            return None
        facts = _validated_facts(
            article.facts,
            summary=article.summary,
            target_status=article.target_status,
        )
        if facts.opportunity_kind != OpportunityKind.STATUS_MATCH:
            return None
        return MatchOpportunitySummary(
            opportunity_id=article.id,
            source="ORDINARY_ARTICLE",
            opportunity_kind=facts.opportunity_kind,
            program=article.program,
            target_status=article.target_status,
            summary=article.summary,
            lifecycle_status=effective_status(article, now=now),
            path=path,
            deadline=facts.deadline.value,
            conflict=_has_conflict(facts),
        )

    def _standalone_article_matches(
        self, current: datetime
    ) -> list[MatchOpportunitySummary]:
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
        latest: dict[UUID, ArticleAnalysisRecord] = {}
        for analysis in analyses:
            latest.setdefault(analysis.source_item_id, analysis)
        routed_documents = set(
            self._session.scalars(select(StatusMatchArticleRoute.document_version_id))
        )
        result: list[MatchOpportunitySummary] = []
        for analysis in latest.values():
            if analysis.document_version_id in routed_documents:
                continue
            for article in self._session.scalars(
                select(ArticleOpportunityRecord)
                .where(ArticleOpportunityRecord.analysis_id == analysis.id)
                .order_by(ArticleOpportunityRecord.opportunity_index)
            ):
                if not contributes(article, now=current):
                    continue
                facts = _validated_facts(
                    article.facts,
                    summary=article.summary,
                    target_status=article.target_status,
                )
                if (
                    facts.opportunity_kind != OpportunityKind.STATUS_MATCH
                    or facts.status_mappings
                ):
                    continue
                result.append(
                    MatchOpportunitySummary(
                        opportunity_id=article.id,
                        source="ORDINARY_ARTICLE",
                        opportunity_kind=facts.opportunity_kind,
                        program=article.program,
                        target_status=article.target_status,
                        summary=article.summary,
                        lifecycle_status=effective_status(article, now=current),
                        path=None,
                        deadline=facts.deadline.value,
                        conflict=_has_conflict(facts),
                    )
                )
        return result

    def _standalone_official_matches(self, *, now=None) -> list[MatchOpportunitySummary]:
        result: list[MatchOpportunitySummary] = []
        for watch in self._session.scalars(
            select(StatusMatchWatch).where(
                StatusMatchWatch.current_event_id.is_not(None)
            )
        ):
            event = self._session.get(StatusEvent, watch.current_event_id)
            if event is None or event.current_fact_set_id is None or not contributes(event, now=now):
                continue
            fact_record = self._session.get(FactSetRecord, event.current_fact_set_id)
            if fact_record is None:
                continue
            facts = _validated_facts(
                fact_record.facts,
                summary=event.summary,
                target_status=event.target_status,
                managed_statusmatch=True,
            )
            if facts.status_mappings:
                continue
            result.append(
                MatchOpportunitySummary(
                    opportunity_id=fact_record.id,
                    source="STATUSMATCH_OFFICIAL",
                    opportunity_kind=OpportunityKind.STATUS_MATCH,
                    program=event.program,
                    target_status=event.target_status,
                    summary=event.summary,
                    lifecycle_status=effective_status(event, now=now),
                    path=None,
                    deadline=facts.deadline.value,
                    conflict=_has_conflict(facts),
                )
            )
        return result

    def _official_detail(self, record: FactSetRecord) -> OpportunityDetail:
        event = self._session.get(StatusEvent, record.event_id)
        if event is None:
            raise LookupError("Opportunity event was not found")
        managed = _is_managed_event(self._session, event.id)
        facts = _validated_facts(
            record.facts,
            summary=event.summary,
            target_status=event.target_status,
            managed_statusmatch=managed,
        )
        brief_record = (
            self._session.get(BriefRecord, event.current_brief_id)
            if event.current_brief_id is not None
            else None
        )
        if brief_record is None or brief_record.fact_set_id != record.id:
            brief_record = self._session.scalar(select(BriefRecord)
                .where(BriefRecord.fact_set_id==record.id)
                .order_by(BriefRecord.version.desc()).limit(1))
        brief = (
            read_brief(brief_record.content)
            if brief_record is not None
            else None
        )
        result = _detail(
            opportunity_id=record.id,
            source="STATUSMATCH_OFFICIAL" if managed else "STATUS_EVENT",
            program=event.program,
            target_status=event.target_status,
            summary=event.summary,
            lifecycle_status=effective_status(event),
            facts=facts,
            brief=brief,
        )
        from journeyplus.knowledge.source_documents import source_links
        links = source_links(self._session, record)
        return result.model_copy(update={'source_links': sorted(set(map(str, result.source_links)) | set(links)),
                                         'brief_updated_at': brief_record.updated_at if brief_record else None})

    def _article_detail(self, article: ArticleOpportunityRecord) -> OpportunityDetail:
        facts = _validated_facts(
            article.facts,
            summary=article.summary,
            target_status=article.target_status,
        )
        brief_record = (
            self._session.get(ArticleBriefRecord, article.current_brief_id)
            if article.current_brief_id is not None
            else None
        )
        brief = (
            read_brief(brief_record.content)
            if brief_record is not None
            else None
        )
        result = _detail(
            opportunity_id=article.id,
            source="ORDINARY_ARTICLE",
            program=article.program,
            target_status=article.target_status,
            summary=article.summary,
            lifecycle_status=effective_status(article),
            facts=facts,
            brief=brief,
        )

        from journeyplus.knowledge.source_documents import source_links
        links = source_links(self._session, article)
        return result.model_copy(update={'source_links': sorted(set(map(str, result.source_links)) | set(links)),
                                         'brief_updated_at': brief_record.updated_at if brief_record else None})


def _validated_facts(
    raw_facts: dict,
    *,
    summary: str,
    target_status: str | None,
    managed_statusmatch: bool = False,
) -> FactSet:
    return FactSet.model_validate(
        with_legacy_opportunity_kind(
            raw_facts,
            summary=summary,
            target_status=target_status,
            managed_statusmatch=managed_statusmatch,
        )
    )


def _detail(
    *,
    opportunity_id: UUID,
    source: str,
    program: str,
    target_status: str | None,
    summary: str,
    lifecycle_status: str,
    facts: FactSet,
    brief: Brief | StatusMatchBrief | None,
) -> OpportunityDetail:
    from journeyplus.product.brief_data import action_links, fee_view
    routes = [_route_view(route, facts) for route in facts.application_routes]
    if not routes:
        virtual = _virtual_route(facts)
        if virtual is not None:
            routes.append(virtual)
    source_links = sorted(
        {
            str(evidence.source_url)
            for field in facts.fact_fields().values()
            for evidence in field.evidence
        }
        | {
            str(evidence.source_url)
            for route in facts.application_routes
            for evidence in route.evidence
        }
        | {
            str(evidence.source_url)
            for route in facts.application_routes
            for price in route.prices
            for evidence in price.evidence
        }
        | ({str(value) for value in brief.source_links} if brief else set())
    )
    return OpportunityDetail(
        opportunity_id=opportunity_id,
        fee=fee_view(facts),
        action_links=action_links(facts),
        source=source,
        opportunity_kind=facts.opportunity_kind,
        program=program,
        target_status=target_status,
        summary=summary,
        lifecycle_status=lifecycle_status,
        facts=facts,
        routes=routes,
        brief=brief,
        source_links=source_links,
    )


def _route_view(route: ApplicationRoute, facts: FactSet) -> ProductApplicationRoute:
    region = route.region or facts.region.value
    prices = effective_route_prices(
        route,
        common_cost=facts.cost.value,
        common_evidence=facts.cost.evidence,
    )
    return ProductApplicationRoute(
        scope=route.scope,
        eligibility=route.eligibility or facts.eligibility.value,
        region=region,
        china_advisory=china_region_advisory(region),
        cost=route.cost or facts.cost.value,
        prices=prices,
        action_link=(
            str(route.action_link)
            if route.action_link is not None
            else facts.action_link.value
        ),
        evidence=route.evidence,
        conflict=route.conflict,
        conflict_note=route.conflict_note,
    )


def _virtual_route(facts: FactSet) -> ProductApplicationRoute | None:
    evidence = _merge_evidence(
        facts.eligibility.evidence,
        facts.region.evidence,
        facts.cost.evidence,
        facts.action_link.evidence,
    )
    if not any(
        (
            facts.eligibility.value,
            facts.region.value,
            facts.cost.value,
            facts.action_link.value,
        )
    ):
        return None
    prices = (
        parse_route_prices(facts.cost.value, evidence=facts.cost.evidence)
        if facts.cost.value
        else []
    )
    return ProductApplicationRoute(
        scope="默认申请路线",
        eligibility=facts.eligibility.value,
        region=facts.region.value,
        china_advisory=china_region_advisory(facts.region.value),
        cost=facts.cost.value,
        prices=prices,
        action_link=facts.action_link.value,
        evidence=evidence,
    )


def _merge_evidence(*groups):
    seen = set()
    result = []
    for evidence in (item for group in groups for item in group):
        key = (
            evidence.document_version_id,
            str(evidence.source_url),
            evidence.locator,
        )
        if key not in seen:
            seen.add(key)
            result.append(evidence)
    return result


def _has_conflict(facts: FactSet) -> bool:
    return (
        any(field.conflict for field in facts.fact_fields().values())
        or any(route.conflict for route in facts.application_routes)
        or any(mapping.conflict for mapping in facts.status_mappings)
    )


def _is_managed_event(session: Session, event_id: UUID) -> bool:
    return session.scalar(
        select(StatusMatchWatch.id).where(
            StatusMatchWatch.current_event_id == event_id
        )
    ) is not None


def _fee_labels_for_target(facts: FactSet, target_tier_key: str, *, program_aliases=()) -> list[str]:
    from journeyplus.fee_policy import route_fees
    labels: list[str] = []
    for route in facts.application_routes or [None]:
        policy = route_fees(facts, route, target_tier=target_tier_key, program_aliases=program_aliases)
        if policy.conflict:
            label = "费用存在冲突"
        else:
            label = _route_fee_label([p for _,p in policy.prices],
                target_tier_key=target_tier_key, raw_cost=policy.text, program_aliases=program_aliases)
            if policy.free and not label:
                label = "免费"
            elif policy.free and policy.conditional and "免费" not in label:
                label = "免费；" + label
        if label is not None:
            labels.append(label)
    return list(dict.fromkeys(labels))


def _route_fee_label(
    prices: list[RoutePrice],
    *,
    target_tier_key: str,
    raw_cost: str | None,
    program_aliases=(),
) -> str | None:
    selected = [
        price
        for price in prices
        if price.target_tier is None
        or program_tier_key(price.target_tier, program_aliases) == program_tier_key(target_tier_key, program_aliases)
    ]
    general_available = _rendered_fees(
        selected,
        target_specific=False,
        availability=RoutePriceAvailability.AVAILABLE,
    )
    targeted_available = _rendered_fees(
        selected,
        target_specific=True,
        availability=RoutePriceAvailability.AVAILABLE,
    )
    conditional = list(
        dict.fromkeys(
            label
            for price in selected
            if price.availability == RoutePriceAvailability.CONDITIONAL
            for label in [_render_fee(price)]
            if label is not None
        )
    )
    payable_parts: list[str] = []
    if general_available:
        payable_parts.append(" + ".join(general_available))
    if targeted_available:
        payable_parts.append(" / ".join(targeted_available))
    payable = " + ".join(payable_parts)
    if payable and conditional:
        return f"{payable}；{' / '.join(conditional)}"
    if payable:
        return payable
    if conditional:
        return " / ".join(conditional)
    if raw_cost and _FREE_COST.fullmatch(raw_cost):
        return "免费"
    if raw_cost and "金额未公布" in raw_cost and "收费" in raw_cost:
        return "金额未公布"
    return None


def _render_fee(price: RoutePrice) -> str | None:
    if price.availability == RoutePriceAvailability.UNAVAILABLE:
        return None
    if price.amount is None or price.currency is None:
        return None
    if price.amount == 0:
        return "免费"
    rendered = f"{price.currency} {_decimal_text(price.amount)}"
    if price.availability == RoutePriceAvailability.CONDITIONAL:
        return f"条件另付 {rendered}"
    return rendered


def _rendered_fees(
    prices: list[RoutePrice],
    *,
    target_specific: bool,
    availability: RoutePriceAvailability,
) -> list[str]:
    return list(
        dict.fromkeys(
            label
            for price in prices
            if (price.target_tier is not None) == target_specific
            and price.availability == availability
            for label in [_render_fee(price)]
            if label is not None
        )
    )


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _opportunity_paths(
    roots: list[ReachableMembershipTreeNode],
) -> dict[UUID, list[str]]:
    adjacency: dict[str, list[ReachableMembershipTreeEdge]] = {}
    seen_edges: set[tuple[str, str]] = set()

    def collect(node: ReachableMembershipTreeNode) -> None:
        for edge in node.children:
            edge_key = (edge.source_node_id, edge.target_node_id)
            if (
                edge.child.state != UnifiedTreeNodeState.CYCLE
                and edge_key not in seen_edges
            ):
                seen_edges.add(edge_key)
                adjacency.setdefault(edge.source_node_id, []).append(edge)
            collect(edge.child)

    for root in roots:
        collect(root)

    result: dict[UUID, list[str]] = {}
    node_paths: dict[str, list[str]] = {}
    queue: deque[str] = deque()
    for root in roots:
        if root.node.id in node_paths:
            continue
        node_paths[root.node.id] = [root.node.id]
        queue.append(root.node.id)

    while queue:
        source_node_id = queue.popleft()
        source_path = node_paths[source_node_id]
        for edge in adjacency.get(source_node_id, []):
            child_path = [*source_path, edge.target_node_id]
            for opportunity_id in edge.opportunity_ids:
                existing = result.get(opportunity_id)
                if existing is None or len(child_path) < len(existing):
                    result[opportunity_id] = child_path
            if edge.target_node_id not in node_paths:
                node_paths[edge.target_node_id] = child_path
                queue.append(edge.target_node_id)
    return result
