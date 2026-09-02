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
        resolved_limits = limits or UnifiedTraversalLimits()
        counters = TraversalCounters()

        def make_node(
            node_id: str,
            node_state: str,
            children: list[UnifiedMembershipTreeEdge],
            omitted_count: int,
        ) -> UnifiedMembershipTreeNode:
            return UnifiedMembershipTreeNode(
                node=state.nodes[node_id],
                state=UnifiedTreeNodeState(node_state),
                children=children,
                omitted_count=omitted_count,
            )

        def make_edge(
            source_id: str,
            target_id: str,
            relation: _Outgoing,
            child: UnifiedMembershipTreeNode,
        ) -> UnifiedMembershipTreeEdge:
            contributions = relation.contributions
            return UnifiedMembershipTreeEdge(
                source_node_id=source_id,
                target_node_id=target_id,
                certainties=sorted(
                    {item.certainty for item in contributions},
                    key=certainty_rank,
                ),
                conditions=sorted(
                    {
                        item.conditions
                        for item in contributions
                        if item.conditions is not None
                    },
                    key=str.casefold,
                ),
                derived_from_rule=relation.derived_from_rule,
                conditional=any(
                    item.availability == MappingAvailability.CONDITIONAL
                    for item in contributions
                ),
                conflict=any(item.conflict for item in contributions),
                child=child,
            )

        root_tree = expand_bounded_tree(
            root.id,
            depth=0,
            ancestors={root.id},
            expanded=set(),
            counters=counters,
            limits=resolved_limits,
            outgoing=lambda node_id: _outgoing(state, state.nodes[node_id]),
            target_id=lambda relation: relation.target_node_id,
            make_node=make_node,
            make_edge=make_edge,
        )
        return UnifiedMembershipTree(
            root=root_tree,
            limits=resolved_limits,
            occurrence_count=counters.occurrences,
            expanded_node_count=counters.expanded,
            cycle_count=counters.cycles,
            cross_reference_count=counters.cross_references,
            truncated_count=counters.truncated,
        )

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
            raise ValueError("technical_node_limit must be positive")
        state = self._build_state(now=now)
        root_ids = sorted(set(root_node_ids))
        missing = [node_id for node_id in root_ids if node_id not in state.nodes]
        if missing:
            raise LookupError(f"Unknown membership nodes: {', '.join(missing)}")

        expanded: set[str] = set()
        occurrences = 0
        expanded_count = 0
        cycle_count = 0
        cross_reference_count = 0
        truncated_count = 0

        def make_reference(node_id: str, node_state: UnifiedTreeNodeState) -> ReachableMembershipTreeNode:
            return ReachableMembershipTreeNode(
                node=state.nodes[node_id],
                state=node_state,
                children=[],
            )

        def make_edge(
            relation: _Outgoing,
            child: ReachableMembershipTreeNode,
        ) -> ReachableMembershipTreeEdge:
            contributions = relation.contributions
            return ReachableMembershipTreeEdge(
                source_node_id=relation.source_node_id,
                target_node_id=relation.target_node_id,
                contribution_ids=[item.contribution_id for item in contributions],
                opportunity_ids=sorted(
                    {item.provenance.subject_id for item in contributions},
                    key=str,
                ),
                certainties=sorted(
                    {item.certainty for item in contributions},
                    key=certainty_rank,
                ),
                conditions=sorted(
                    {
                        item.conditions
                        for item in contributions
                        if item.conditions is not None
                    },
                    key=str.casefold,
                ),
                derived_from_rule=relation.derived_from_rule,
                conditional=any(
                    item.availability == MappingAvailability.CONDITIONAL
                    for item in contributions
                ),
                conflict=any(item.conflict for item in contributions),
                child=child,
            )

        def expand(node_id: str, ancestors: frozenset[str]) -> ReachableMembershipTreeNode:
            nonlocal occurrences, expanded_count, cycle_count
            nonlocal cross_reference_count, truncated_count
            occurrences += 1
            expanded.add(node_id)
            expanded_count += 1
            relations = _outgoing(state, state.nodes[node_id])
            if not relations:
                return make_reference(node_id, UnifiedTreeNodeState.LEAF)
            children: list[ReachableMembershipTreeEdge] = []
            omitted = 0
            for index, relation in enumerate(relations):
                child_id = relation.target_node_id
                if occurrences >= technical_node_limit:
                    omitted = len(relations) - index
                    truncated_count += omitted
                    break
                if child_id in ancestors:
                    occurrences += 1
                    cycle_count += 1
                    child = make_reference(child_id, UnifiedTreeNodeState.CYCLE)
                elif child_id in expanded:
                    occurrences += 1
                    cross_reference_count += 1
                    child = make_reference(
                        child_id, UnifiedTreeNodeState.CROSS_REFERENCE
                    )
                else:
                    child = expand(child_id, ancestors | {child_id})
                children.append(make_edge(relation, child))
            return ReachableMembershipTreeNode(
                node=state.nodes[node_id],
                state=(
                    UnifiedTreeNodeState.NODE_LIMIT
                    if omitted
                    else UnifiedTreeNodeState.EXPANDED
                ),
                children=children,
                omitted_count=omitted,
            )

        roots: list[ReachableMembershipTreeNode] = []
        for root_id in root_ids:
            if occurrences >= technical_node_limit:
                truncated_count += 1
                roots.append(
                    make_reference(root_id, UnifiedTreeNodeState.NODE_LIMIT)
                )
            elif root_id in expanded:
                occurrences += 1
                cross_reference_count += 1
                roots.append(
                    make_reference(root_id, UnifiedTreeNodeState.CROSS_REFERENCE)
                )
            else:
                roots.append(expand(root_id, frozenset({root_id})))
        return ReachableMembershipForest(
            roots=roots,
            technical_node_limit=technical_node_limit,
            occurrence_count=occurrences,
            expanded_node_count=expanded_count,
            cycle_count=cycle_count,
            cross_reference_count=cross_reference_count,
            truncated_count=truncated_count,
        )

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
        official = StatusMatchOfficialContributionAdapter(self._session).read()
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
    tier_label = display_tier(tier)
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
    raw_tokens = display_text(value).split()
    normalized_tokens = [normalize_key(item) for item in raw_tokens]
    for alias in sorted(aliases, key=lambda item: -len(normalize_key(item).split())):
        alias_tokens = normalize_key(alias).split()
        if normalized_tokens[: len(alias_tokens)] == alias_tokens:
            remainder = raw_tokens[len(alias_tokens) :]
            if remainder:
                return display_tier(" ".join(remainder))
    return display_tier(value)


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
