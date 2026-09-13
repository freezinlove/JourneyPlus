from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from journeyplus.contracts import MappingAvailability
from journeyplus.membership.alliances import airline_alliance
from journeyplus.membership.contracts import (
    ContributionCertainty,
    ExcludedMappingContribution,
    MembershipMappingContribution,
    MembershipCatalog,
    MembershipProgramCategory,
    ReachableMembershipForest,
    ReachableMembershipTreeEdge,
    ReachableMembershipTreeNode,
    UnifiedMembershipAudit,
    UnifiedMembershipEdgeAudit,
    UnifiedMembershipNode,
    UnifiedMembershipTree,
    UnifiedMembershipTreeEdge,
    UnifiedMembershipTreeNode,
    UnifiedTraversalLimits,
    UnifiedTreeNodeState,
)
from journeyplus.membership.contributions import (
    OrdinaryArticleContributionAdapter,
    StatusMatchOfficialContributionAdapter,
)
from journeyplus.membership.normalization import (
    certainty_rank,
    display_text,
    display_tier,
    group_by_source,
    normalize_key,
    normalize_tier,
    resolve_alias,
    stable_id,
    strip_program_prefix,
)
from journeyplus.membership.traversal import (
    TraversalCounters,
    expand_bounded_tree,
)


@dataclass(slots=True)
class _Program:
    key: str
    label: str
    aliases: set[str] = field(default_factory=set)
    categories: set[MembershipProgramCategory] = field(default_factory=set)


class _Registry:
    def __init__(self) -> None:
        self.programs: dict[str, _Program] = {}
        self.aliases: dict[str, set[str]] = defaultdict(set)
        self.ambiguities: dict[str, set[str]] = defaultdict(set)

    def seed(self, key: str, label: str, aliases: list[str], categories) -> None:
        record = self.programs.setdefault(
            key, _Program(key=key, label=display_text(label))
        )
        for category in categories:
            record.categories.add(MembershipProgramCategory(str(category)))
        for alias in {label, *aliases}:
            displayed = display_text(alias)
            record.aliases.add(displayed)
            self.aliases[normalize_key(displayed)].add(key)

    def resolve(self, raw_program: str) -> str:
        from journeyplus.membership.identity import canonical_program, program_record
        raw_program = canonical_program(raw_program)
        resolution = resolve_alias(raw_program, self.aliases)
        candidates = set(resolution.candidates)
        if len(candidates) == 1:
            key = next(iter(candidates))
        else:
            key = resolution.normalized
            if len(candidates) > 1:
                self.ambiguities[resolution.label].update(candidates)
        record = self.programs.setdefault(
            key, _Program(key=key, label=resolution.label)
        )
        record.aliases.add(resolution.label)
        self.aliases[resolution.normalized].add(key)
        known = program_record(raw_program)
        if known and known['category'] in {'AIRLINE','HOTEL'}:
            record.categories.add(MembershipProgramCategory(known['category']))
        return key


@dataclass(slots=True)
class _Edge:
    source_node_id: str
    target_node_id: str
    contributions: dict[str, MembershipMappingContribution] = field(
        default_factory=dict
    )


@dataclass(slots=True)
class _Rule:
    source_program_key: str | None
    source_category: MembershipProgramCategory
    source_tier_key: str | None
    target_node_id: str
    contributions: dict[str, MembershipMappingContribution] = field(
        default_factory=dict
    )


@dataclass(slots=True)
class _State:
    registry: _Registry
    nodes: dict[str, UnifiedMembershipNode]
    edges: dict[tuple[str, str], _Edge]
    edges_by_source: dict[str, list[_Edge]]
    rules: list[_Rule]
    contributions: tuple[MembershipMappingContribution, ...]
    excluded: tuple[ExcludedMappingContribution, ...]
    official_unavailable_count: int


@dataclass(frozen=True, slots=True)
class _Outgoing:
    source_node_id: str
    target_node_id: str
    contributions: tuple[MembershipMappingContribution, ...]
    derived_from_rule: bool


class UnifiedMembershipTreeService:
    """Deterministic read projection over official and ordinary article mappings."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def tree(
        self,
        program: str,
        tier: str,
        *,
        limits: UnifiedTraversalLimits | None = None,
        now: datetime | None = None,
    ) -> UnifiedMembershipTree:
        state = self._build_state(now=now)
        root = self._query_node(state, program, tier)
        limits = limits or UnifiedTraversalLimits()
        from journeyplus.knowledge.workflow_routes import matching_forest
        forest = matching_forest(self._session,[root.id], technical_node_limit=limits.max_nodes, now=now,state=state)
        omitted = 0
        def convert(node, depth):
            nonlocal omitted
            chosen = node.children[:limits.max_branches] if depth < limits.max_depth else []
            missing = len(node.children)-len(chosen)
            omitted += missing
            children = [UnifiedMembershipTreeEdge(source_node_id=e.source_node_id,
                target_node_id=e.target_node_id, certainties=e.certainties, derived_from_rule=e.derived_from_rule, child=convert(e.child,depth+1)) for e in chosen]
            return UnifiedMembershipTreeNode(node=node.node, state='DEPTH_LIMIT' if missing else node.state,
                children=children, omitted_count=missing)
        tree = convert(forest.roots[0],0)
        def count(node): return 1+sum(count(e.child) for e in node.children)
        return UnifiedMembershipTree(root=tree, limits=limits, occurrence_count=count(tree),
            expanded_node_count=count(tree), cycle_count=0, cross_reference_count=0,
            truncated_count=forest.truncated_count+omitted)

    def catalog(
        self,
        *,
        query: str | None = None,
        now: datetime | None = None,
    ) -> MembershipCatalog:
        state = self._build_state(now=now)
        normalized_query = normalize_key(query) if query else None
        nodes = sorted(
            (
                node
                for node in state.nodes.values()
                if normalized_query is None
                or normalized_query in normalize_key(f"{node.program} {node.tier}")
            ),
            key=lambda node: (
                node.program.casefold(),
                node.tier.casefold(),
                node.id,
            ),
        )
        return MembershipCatalog(nodes=nodes)

    def reachable_forest(
        self,
        root_node_ids: list[str] | tuple[str, ...],
        *,
        technical_node_limit: int = 5000,
        now: datetime | None = None,
    ) -> ReachableMembershipForest:
        if technical_node_limit < 1:
            raise ValueError('technical_node_limit must be positive')
        from journeyplus.knowledge.workflow_routes import matching_forest
        return matching_forest(self._session, root_node_ids, technical_node_limit=technical_node_limit, now=now)

    def audit(self, *, now: datetime | None = None) -> UnifiedMembershipAudit:
        state = self._build_state(now=now)
        excluded_counts = Counter(item.reason for item in state.excluded)
        if state.official_unavailable_count:
            excluded_counts["OFFICIAL_UNAVAILABLE"] += state.official_unavailable_count
        edges = [
            UnifiedMembershipEdgeAudit(
                edge_id=stable_id("unified-edge", source, target),
                source_node_id=source,
                target_node_id=target,
                contributions=sorted(
                    edge.contributions.values(),
                    key=lambda item: item.contribution_id,
                ),
            )
            for (source, target), edge in sorted(state.edges.items())
        ]
        return UnifiedMembershipAudit(
            active_contribution_count=len(state.contributions),
            excluded_contribution_count=(
                len(state.excluded) + state.official_unavailable_count
            ),
            excluded_counts=dict(sorted(excluded_counts.items())),
            node_count=len(state.nodes),
            edge_count=len(state.edges),
            rule_count=len(state.rules),
            strongly_connected_components=_strongly_connected_components(
                state.nodes, state.edges
            ),
            edges=edges,
            excluded=list(state.excluded),
            alias_ambiguities={
                key: sorted(values)
                for key, values in sorted(state.registry.ambiguities.items())
            },
        )

    def _build_state(self, *, now: datetime | None) -> _State:
        official = StatusMatchOfficialContributionAdapter(self._session).read(now=now)
        ordinary = OrdinaryArticleContributionAdapter(self._session).read(now=now)
        assert official.snapshot is not None
        snapshot = official.snapshot
        registry = _Registry()
        for program in snapshot.programs:
            registry.seed(
                program.key,
                program.label,
                program.aliases,
                program.categories,
            )
        nodes = {
            item.id: UnifiedMembershipNode(
                id=item.id,
                program_key=item.program_key,
                tier_key=item.tier_key,
                program=item.program,
                tier=item.tier,
                categories=[
                    MembershipProgramCategory(str(value)) for value in item.categories
                ],
                alliance=airline_alliance(item.program)
                if MembershipProgramCategory.AIRLINE
                in {
                    MembershipProgramCategory(str(value))
                    for value in item.categories
                }
                else None,
            )
            for item in snapshot.nodes
        }
        edges: dict[tuple[str, str], _Edge] = {}
        rules_by_key: dict[
            tuple[
                str | None,
                MembershipProgramCategory,
                str | None,
                str,
            ],
            _Rule,
        ] = {}
        contribution_by_id = {
            item.contribution_id: item for item in official.contributions
        }
        for edge in snapshot.edges:
            key = (edge.source_node_id, edge.target_node_id)
            target = edges.setdefault(key, _Edge(*key))
            for claim in edge.claims:
                contribution = contribution_by_id[f"official:{claim.id}"]
                target.contributions[contribution.contribution_id] = contribution
        for rule in snapshot.rules:
            category = MembershipProgramCategory(str(rule.source_category))
            key = (
                rule.source_program_key,
                category,
                rule.source_tier_key,
                rule.target_node_id,
            )
            target_rule = rules_by_key.setdefault(
                key,
                _Rule(
                    source_program_key=rule.source_program_key,
                    source_category=category,
                    source_tier_key=rule.source_tier_key,
                    target_node_id=rule.target_node_id,
                ),
            )
            for claim in rule.claims:
                contribution = contribution_by_id[f"official:{claim.id}"]
                target_rule.contributions[contribution.contribution_id] = contribution

        for contribution in ordinary.contributions:
            source_key = registry.resolve(contribution.source_program)
            target_key = registry.resolve(contribution.target_program)
            source_node = _ensure_node(
                registry,
                nodes,
                program_key=source_key,
                tier=contribution.source_tier,
            )
            target_node = _ensure_node(
                registry,
                nodes,
                program_key=target_key,
                tier=_target_tier(
                    contribution.target_tier,
                    registry.programs[target_key].aliases,
                ),
            )
            edge = edges.setdefault(
                (source_node.id, target_node.id),
                _Edge(source_node.id, target_node.id),
            )
            edge.contributions[contribution.contribution_id] = contribution

        all_contributions = tuple(
            sorted(
                [*official.contributions, *ordinary.contributions],
                key=lambda item: item.contribution_id,
            )
        )
        return _State(
            registry=registry,
            nodes=nodes,
            edges=edges,
            edges_by_source=group_by_source(
                edges.values(), lambda edge: edge.source_node_id
            ),
            rules=list(rules_by_key.values()),
            contributions=all_contributions,
            excluded=ordinary.excluded,
            official_unavailable_count=snapshot.unavailable_mapping_count,
        )

    @staticmethod
    def _query_node(
        state: _State, program: str, tier: str
    ) -> UnifiedMembershipNode:
        program_key = state.registry.resolve(program)
        return _ensure_node(
            state.registry,
            state.nodes,
            program_key=program_key,
            tier=tier,
        )

def _ensure_node(
    registry: _Registry,
    nodes: dict[str, UnifiedMembershipNode],
    *,
    program_key: str,
    tier: str,
) -> UnifiedMembershipNode:
    record = registry.programs[program_key]
    from journeyplus.membership.identity import canonical_tier
    tier_label = display_tier(canonical_tier(record.label, tier))
    node_id = f"{program_key}::{normalize_tier(tier_label)}"
    node = nodes.get(node_id)
    if node is None:
        categories = sorted(record.categories, key=str)
        node = UnifiedMembershipNode(
            id=node_id,
            program_key=program_key,
            tier_key=normalize_tier(tier_label),
            program=record.label,
            tier=tier_label,
            categories=categories,
            alliance=airline_alliance(record.label)
            if MembershipProgramCategory.AIRLINE in categories
            else None,
        )
        nodes[node_id] = node
    return node


def _target_tier(value: str, aliases: set[str]) -> str:
    return display_tier(strip_program_prefix(value, aliases))


def _outgoing(state: _State, node: UnifiedMembershipNode) -> list[_Outgoing]:
    grouped: dict[str, dict[str, object]] = {}
    for edge in state.edges_by_source.get(node.id, []):
        grouped[edge.target_node_id] = {
            "contributions": dict(edge.contributions),
            "derived": False,
        }
    node_categories = set(node.categories)
    for rule in state.rules:
        if rule.source_program_key is not None:
            if rule.source_program_key != node.program_key:
                continue
        elif rule.source_category not in node_categories:
            continue
        if (
            rule.source_tier_key is not None
            and rule.source_tier_key != node.tier_key
        ):
            continue
        item = grouped.setdefault(
            rule.target_node_id, {"contributions": {}, "derived": False}
        )
        contributions = item["contributions"]
        assert isinstance(contributions, dict)
        contributions.update(rule.contributions)
        item["derived"] = True
    relations = [
        _Outgoing(
            source_node_id=node.id,
            target_node_id=target,
            contributions=tuple(
                sorted(
                    item["contributions"].values(),
                    key=lambda contribution: contribution.contribution_id,
                )
            ),
            derived_from_rule=bool(item["derived"]),
        )
        for target, item in grouped.items()
    ]
    return sorted(
        relations,
        key=lambda item: (
            state.nodes[item.target_node_id].program.casefold(),
            state.nodes[item.target_node_id].tier.casefold(),
        ),
    )


def _strongly_connected_components(
    nodes: dict[str, UnifiedMembershipNode],
    edges: dict[tuple[str, str], _Edge],
) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        adjacency[source].append(target)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    result: list[list[str]] = []

    def visit(node_id: str) -> None:
        nonlocal index
        indexes[node_id] = lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)
        for target in adjacency.get(node_id, []):
            if target not in indexes:
                visit(target)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
            elif target in on_stack:
                lowlinks[node_id] = min(lowlinks[node_id], indexes[target])
        if lowlinks[node_id] != indexes[node_id]:
            return
        component: list[str] = []
        while stack:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node_id:
                break
        if len(component) > 1 or node_id in adjacency.get(node_id, []):
            result.append(sorted(component))

    for node_id in sorted(nodes):
        if node_id not in indexes:
            visit(node_id)
    return sorted(result)
