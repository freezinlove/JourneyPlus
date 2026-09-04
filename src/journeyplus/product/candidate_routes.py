from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from itertools import product
from uuid import UUID

from journeyplus.contracts import RoutePriceAvailability
from journeyplus.membership.contracts import (
    ReachableMembershipTreeEdge,
    ReachableMembershipTreeNode,
    UnifiedMembershipNode,
    UnifiedTreeNodeState,
)
from journeyplus.membership.alliances import airline_alliance
from journeyplus.membership.normalization import normalize_key, normalize_tier
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.product.contracts import (
    CandidateChallengePolicy,
    CandidateCostPolicy,
    CandidateRoute,
    CandidateRouteQuery,
    CandidateRouteResult,
    CandidateRouteStep,
    CandidateRelativeTier,
    OpportunityDetail,
)
from journeyplus.product.holdings import StatusHoldingService
from journeyplus.product.opportunities import PersonalizedMatchService


_FREE_COST = re.compile(
    r"^\s*(?:免费|无费用|无需付费|free(?:\s+of\s+charge)?)\s*[。.]?\s*$",
    re.IGNORECASE,
)
_UNKNOWN_COST = re.compile(
    r"(?:金额未公布|费用未知|待公布|unknown|not\s+(?:published|disclosed))",
    re.IGNORECASE,
)
_PAID_COST = re.compile(
    r"(?:收费|付费|application\s+fee|service\s+fee|\b(?:USD|EUR|GBP|CNY|RMB|AUD|CAD|JPY|AED)\b|[$€£¥])",
    re.IGNORECASE,
)
_NO_CHALLENGE = re.compile(
    r"(?:无需|没有|无|不要求)\s*(?:飞行|住宿|挑战)|no\s+(?:status\s+)?challenge|instant\s+match|direct\s+match",
    re.IGNORECASE,
)
_CHALLENGE = re.compile(
    r"(?:挑战|status\s+challenge|challenge|完成.{0,20}(?:飞行|航段|住宿|晚)|(?:fly|flight|stay|night|spend).{0,30}(?:within|in)\s+\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _GraphEdge:
    source_node_id: str
    target_node_id: str
    opportunity_ids: tuple[UUID, ...]
    conditions: tuple[str, ...]
    conflict: bool


class CandidateRouteService:
    """Return fact-classified routes; never choose a recommendation."""

    def __init__(self, session) -> None:
        self._session = session

    def query(
        self,
        request: CandidateRouteQuery,
        *,
        holding_node_ids: list[str] | tuple[str, ...] | None = None,
        technical_node_limit: int = 5000,
        max_path_steps: int = 6,
        max_candidates: int = 100,
    ) -> CandidateRouteResult:
        if min(technical_node_limit, max_path_steps, max_candidates) < 1:
            raise ValueError("candidate route limits must be positive")
        holdings = StatusHoldingService(self._session).list()
        if holding_node_ids is not None:
            allowed = set(holding_node_ids)
            holdings = [item for item in holdings if item.node_id in allowed]
        if not holdings:
            return CandidateRouteResult(
                query=request,
                holdings=[],
                matching_signature=_matching_signature([]),
            )

        tree_service = UnifiedMembershipTreeService(self._session)
        forest = tree_service.reachable_forest(
            [item.node_id for item in holdings],
            technical_node_limit=technical_node_limit,
        )
        nodes, adjacency = _flatten_forest(forest.roots)
        paths = _target_paths(
            forest.roots,
            nodes,
            adjacency,
            request,
            max_path_steps=max_path_steps,
            max_paths=max_candidates,
        )
        detail_service = PersonalizedMatchService(self._session)
        detail_cache: dict[UUID, OpportunityDetail | None] = {}
        candidates: list[CandidateRoute] = []
        for node_path, edge_path in paths:
            option_groups = [edge.opportunity_ids for edge in edge_path]
            if any(not group for group in option_groups):
                continue
            for opportunity_ids in product(*option_groups):
                details: list[OpportunityDetail] = []
                missing = False
                for opportunity_id in opportunity_ids:
                    if opportunity_id not in detail_cache:
                        try:
                            detail_cache[opportunity_id] = detail_service.detail(
                                opportunity_id,
                                include_current_path=False,
                            )
                        except LookupError:
                            detail_cache[opportunity_id] = None
                    detail = detail_cache[opportunity_id]
                    if detail is None:
                        missing = True
                        break
                    details.append(detail)
                if missing:
                    continue
                candidate = _candidate(
                    request,
                    node_path,
                    edge_path,
                    tuple(opportunity_ids),
                    details,
                    nodes[node_path[-1]],
                )
                candidates.append(candidate)
                if len(candidates) >= max_candidates:
                    break
            if len(candidates) >= max_candidates:
                break

        unique = {item.route_id: item for item in candidates}
        ordered = sorted(
            unique.values(),
            key=lambda item: (len(item.steps), item.node_path, item.route_id),
        )
        matching = [item for item in ordered if not item.violations and not item.unknowns]
        nearby = [
            item
            for item in ordered
            if len(item.violations) == 1 and not item.unknowns
        ]
        unknown = [item for item in ordered if item.unknowns]
        return CandidateRouteResult(
            query=request,
            holdings=holdings,
            matching_routes=matching,
            nearby_routes=nearby,
            unknown_routes=unknown,
            matching_signature=_matching_signature(matching),
        )


def _flatten_forest(
    roots: list[ReachableMembershipTreeNode],
) -> tuple[dict[str, UnifiedMembershipNode], dict[str, list[_GraphEdge]]]:
    nodes: dict[str, UnifiedMembershipNode] = {}
    adjacency: dict[str, list[_GraphEdge]] = {}
    seen: set[tuple[str, str, tuple[UUID, ...]]] = set()

    def visit(node: ReachableMembershipTreeNode) -> None:
        nodes[node.node.id] = node.node
        for edge in node.children:
            nodes[edge.child.node.id] = edge.child.node
            opportunity_ids = tuple(sorted(set(edge.opportunity_ids), key=str))
            key = (edge.source_node_id, edge.target_node_id, opportunity_ids)
            if edge.child.state != UnifiedTreeNodeState.CYCLE and key not in seen:
                seen.add(key)
                adjacency.setdefault(edge.source_node_id, []).append(
                    _GraphEdge(
                        source_node_id=edge.source_node_id,
                        target_node_id=edge.target_node_id,
                        opportunity_ids=opportunity_ids,
                        conditions=tuple(edge.conditions),
                        conflict=edge.conflict,
                    )
                )
            visit(edge.child)

    for root in roots:
        visit(root)
    for edges in adjacency.values():
        edges.sort(
            key=lambda edge: (
                edge.target_node_id,
                tuple(str(item) for item in edge.opportunity_ids),
            )
        )
    return nodes, adjacency


def _target_paths(
    roots: list[ReachableMembershipTreeNode],
    nodes: dict[str, UnifiedMembershipNode],
    adjacency: dict[str, list[_GraphEdge]],
    request: CandidateRouteQuery,
    *,
    max_path_steps: int,
    max_paths: int,
) -> list[tuple[list[str], list[_GraphEdge]]]:
    result: list[tuple[list[str], list[_GraphEdge]]] = []
    queue: deque[tuple[list[str], list[_GraphEdge]]] = deque(
        ([root.node.id], []) for root in roots
    )
    while queue and len(result) < max_paths:
        node_path, edge_path = queue.popleft()
        if len(edge_path) >= max_path_steps:
            continue
        for edge in adjacency.get(node_path[-1], []):
            if edge.target_node_id in node_path:
                continue
            next_nodes = [*node_path, edge.target_node_id]
            next_edges = [*edge_path, edge]
            target_node = nodes[edge.target_node_id]
            if _matches_target(target_node, request):
                result.append((next_nodes, next_edges))
                if len(result) >= max_paths:
                    break
            queue.append((next_nodes, next_edges))
    return result


def _matches_target(node: UnifiedMembershipNode, request: CandidateRouteQuery) -> bool:
    target = request.target
    if target.program_key is not None and node.program_key != normalize_key(target.program_key):
        return False
    if target.tier_key is not None and node.tier_key != normalize_tier(target.tier_key):
        return False
    if target.alliance is not None and _node_alliance(node) != target.alliance:
        return False
    return True


def _candidate(
    request: CandidateRouteQuery,
    node_path: list[str],
    edge_path: list[_GraphEdge],
    opportunity_ids: tuple[UUID, ...],
    details: list[OpportunityDetail],
    target_node: UnifiedMembershipNode,
) -> CandidateRoute:
    steps = [
        _step(edge, opportunity_id, detail)
        for edge, opportunity_id, detail in zip(
            edge_path, opportunity_ids, details, strict=True
        )
    ]
    violations: list[str] = []
    unknowns: list[str] = []
    constraints = request.constraints
    if constraints.cost_policy == CandidateCostPolicy.FREE_ONLY:
        cost_state = _free_route_state(details)
        if cost_state == "PAID":
            violations.append("cost_policy")
        elif cost_state == "UNKNOWN":
            unknowns.append("cost_policy")
    elif constraints.cost_policy == CandidateCostPolicy.MAX_AMOUNT:
        assert constraints.max_amount is not None
        assert constraints.max_currency is not None
        total = _route_amount(details, constraints.max_currency)
        if total is None:
            unknowns.append("max_amount")
        elif total > constraints.max_amount:
            violations.append("max_amount")

    if constraints.challenge_policy == CandidateChallengePolicy.NO_CHALLENGE:
        challenge_state = _challenge_state(details, edge_path)
        if challenge_state == "CHALLENGE":
            violations.append("challenge_policy")
        elif challenge_state == "UNKNOWN":
            unknowns.append("challenge_policy")

    limitations: list[str] = []
    if request.target.relative_tier == CandidateRelativeTier.HIGH:
        limitations.append("现有数据未结构化联盟精英等级等价，目标等级由 Agent 结合候选名称判断。")
    if any(step.conflict for step in steps):
        limitations.append("路线包含存在冲突标记的正式事实，申请前需核对原始证据。")
    identity = "|".join(
        [*node_path, *(str(item) for item in opportunity_ids)]
    )
    return CandidateRoute(
        route_id=sha256(identity.encode()).hexdigest()[:24],
        node_path=node_path,
        target_program=target_node.program,
        target_tier=target_node.tier,
        target_alliance=_node_alliance(target_node),
        steps=steps,
        violations=violations,
        unknowns=unknowns,
        limitations=limitations,
    )


def _step(
    edge: _GraphEdge,
    opportunity_id: UUID,
    detail: OpportunityDetail,
) -> CandidateRouteStep:
    costs: list[str] = []
    action_links: list[str] = []
    for route in detail.routes:
        if route.cost:
            costs.append(route.cost)
        costs.extend(price.raw_text for price in route.prices)
        if route.action_link:
            action_links.append(route.action_link)
    return CandidateRouteStep(
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        opportunity_id=opportunity_id,
        source=detail.source,
        program=detail.program,
        target_status=detail.target_status,
        summary=detail.summary,
        lifecycle_status=detail.lifecycle_status,
        conditions=list(edge.conditions),
        challenge_requirements=detail.facts.challenge_requirements.value,
        costs=list(dict.fromkeys(costs)),
        deadline=detail.facts.deadline.value,
        conflict=detail.facts.challenge_requirements.conflict
        or detail.facts.cost.conflict
        or any(route.conflict for route in detail.routes)
        or edge.conflict,
        evidence_links=detail.source_links,
        action_links=list(dict.fromkeys(action_links)),
    )


def _free_route_state(details: list[OpportunityDetail]) -> str:
    states = [_opportunity_free_state(detail) for detail in details]
    if all(state == "FREE" for state in states):
        return "FREE"
    if any(state == "UNKNOWN" for state in states):
        return "UNKNOWN"
    return "PAID"


def _opportunity_free_state(detail: OpportunityDetail) -> str:
    if not detail.routes:
        return "UNKNOWN"
    states: list[str] = []
    for route in detail.routes:
        available_prices = [
            price
            for price in route.prices
            if price.availability == RoutePriceAvailability.AVAILABLE
        ]
        if any(price.amount == 0 for price in available_prices):
            states.append("FREE")
        elif available_prices and all(
            price.amount is not None and price.amount > 0 for price in available_prices
        ):
            states.append("PAID")
        elif route.cost and _FREE_COST.fullmatch(route.cost):
            states.append("FREE")
        elif route.cost and _UNKNOWN_COST.search(route.cost):
            states.append("UNKNOWN")
        elif route.cost and _PAID_COST.search(route.cost):
            states.append("PAID")
        else:
            states.append("UNKNOWN")
    if "FREE" in states:
        return "FREE"
    if states and all(state == "PAID" for state in states):
        return "PAID"
    return "UNKNOWN"


def _route_amount(details: list[OpportunityDetail], currency: str) -> Decimal | None:
    total = Decimal("0")
    for detail in details:
        amounts: list[Decimal] = []
        if _opportunity_free_state(detail) == "FREE":
            amounts.append(Decimal("0"))
        for route in detail.routes:
            for price in route.prices:
                if (
                    price.availability == RoutePriceAvailability.AVAILABLE
                    and price.currency == currency
                    and price.amount is not None
                ):
                    amounts.append(price.amount)
        if not amounts:
            return None
        total += min(amounts)
    return total


def _challenge_state(
    details: list[OpportunityDetail], edge_path: list[_GraphEdge]
) -> str:
    texts = [
        text
        for text in (
            *(detail.facts.challenge_requirements.value for detail in details),
            *(condition for edge in edge_path for condition in edge.conditions),
        )
        if text
    ]
    if any(_NO_CHALLENGE.search(text) for text in texts):
        if not any(_CHALLENGE.search(text) and not _NO_CHALLENGE.search(text) for text in texts):
            return "NO_CHALLENGE"
    if any(_CHALLENGE.search(text) for text in texts):
        return "CHALLENGE"
    return "UNKNOWN"


def _matching_signature(routes: list[CandidateRoute]) -> str:
    value = "\x1f".join(sorted(route.route_id for route in routes))
    return sha256(value.encode()).hexdigest()


def _node_alliance(node: UnifiedMembershipNode):
    return node.alliance or airline_alliance(node.program)
