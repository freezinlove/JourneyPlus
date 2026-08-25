from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.contracts import FactSet, MappingAvailability, StatusMapping
from journeyplus.facts.statusmatch_tables import (
    MappingSourceCategory,
    extract_statusmatch_mapping_source_metadata,
)
from journeyplus.models import (
    DocumentVersion,
    FactSetRecord,
    StatusEvent,
    StatusMatchWatch,
    StatusMatchWatchPage,
    StatusMatchArticleSupplement,
)
from journeyplus.membership.contracts import (
    MappingClaimStatus,
    MembershipMappingClaim,
    MembershipMappingLayer,
)
from journeyplus.statusmatch.graph_contracts import (
    AliasAmbiguity,
    ClaimFidelityAudit,
    GraphAuditReport,
    GraphCertainty,
    GraphSnapshot,
    GraphTopologyAudit,
    MappingClaim,
    MembershipEdge,
    MembershipNode,
    MembershipProgram,
    MembershipRule,
    MembershipTree,
    MembershipTreeEdge,
    MembershipTreeNode,
    ProgramCategory,
    TraversalLimits,
    TreeNodeState,
)


_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w+]+", re.UNICODE)
_WILDCARD_PROGRAM_RE = re.compile(r"^\s*(?:all|any|every)\b", re.IGNORECASE)
_WILDCARD_TIER_RE = re.compile(
    r"\b(?:all|any|every)\b.*\b(?:tier|tiers|status|level|levels|membership)\b",
    re.IGNORECASE,
)
_UNCERTAIN_TIER_VALUES = {
    "uncertain",
    "unknown",
    "eligible elite status",
    "elite status",
    "elite member",
    "status holder",
    "membership",
}


@dataclass(slots=True)
class _ProgramRecord:
    key: str
    label: str
    aliases: set[str] = field(default_factory=set)
    categories: set[ProgramCategory] = field(default_factory=set)
    target_program: bool = False


@dataclass(slots=True)
class _NodeRecord:
    id: str
    program_key: str
    tier_key: str
    program: str
    tier: str
    aliases: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _TargetIdentity:
    program_key: str
    aliases: tuple[str, ...]


class _ProgramRegistry:
    def __init__(self) -> None:
        self.records: dict[str, _ProgramRecord] = {}
        self.target_aliases: dict[str, set[str]] = defaultdict(set)
        self.ambiguities: dict[str, set[str]] = defaultdict(set)

    def add_target(self, label: str, target_tiers: Iterable[str]) -> _TargetIdentity:
        key = _normalize_key(label)
        record = self.records.setdefault(
            key,
            _ProgramRecord(key=key, label=_display_text(label)),
        )
        record.target_program = True
        aliases = {_display_text(label)}
        common = _common_target_prefix(target_tiers)
        if common:
            aliases.add(common)
        for alias in aliases:
            record.aliases.add(alias)
            self.target_aliases[_normalize_key(alias)].add(key)
        return _TargetIdentity(
            program_key=key,
            aliases=tuple(sorted(aliases, key=lambda value: (-len(value), value.casefold()))),
        )

    def resolve(self, raw_program: str) -> str:
        label = _display_text(raw_program)
        normalized = _normalize_key(label)
        candidates = set(self.target_aliases.get(normalized, set()))
        best_score: tuple[int, int] | None = None
        suffix_candidates: set[str] = set()
        if not candidates:
            raw_tokens = normalized.split()
            for alias, keys in self.target_aliases.items():
                alias_tokens = alias.split()
                if not _distinctive_alias(alias_tokens):
                    continue
                if len(alias_tokens) > len(raw_tokens):
                    continue
                if raw_tokens[-len(alias_tokens) :] != alias_tokens:
                    continue
                score = (len(alias_tokens), len(alias))
                if best_score is None or score > best_score:
                    best_score = score
                    suffix_candidates = set(keys)
                elif score == best_score:
                    suffix_candidates.update(keys)
            candidates = suffix_candidates
        if len(candidates) == 1:
            key = next(iter(candidates))
        else:
            key = normalized
            if len(candidates) > 1:
                self.ambiguities[label].update(candidates)
        record = self.records.setdefault(
            key,
            _ProgramRecord(key=key, label=label),
        )
        record.aliases.add(label)
        return key

    def add_category(self, program_key: str, category: ProgramCategory) -> None:
        if category != ProgramCategory.UNKNOWN:
            self.records[program_key].categories.add(category)

    def programs(self) -> list[MembershipProgram]:
        return [
            MembershipProgram(
                key=record.key,
                label=record.label,
                aliases=sorted(record.aliases, key=str.casefold),
                categories=sorted(record.categories, key=str),
                target_program=record.target_program,
            )
            for record in sorted(self.records.values(), key=lambda item: item.key)
        ]

    def ambiguity_models(self) -> list[AliasAmbiguity]:
        return [
            AliasAmbiguity(
                raw_program=raw,
                candidate_program_keys=sorted(candidates),
            )
            for raw, candidates in sorted(self.ambiguities.items())
        ]


@dataclass(slots=True)
class _GraphState:
    snapshot: GraphSnapshot
    registry: _ProgramRegistry
    identities: dict[UUID, _TargetIdentity]
    nodes: dict[str, MembershipNode]
    edges_by_source: dict[str, list[MembershipEdge]]
    rules: list[MembershipRule]


@dataclass(slots=True)
class _TreeCounters:
    occurrences: int = 1
    expanded: int = 0
    cycles: int = 0
    cross_references: int = 0
    truncated: int = 0


@dataclass(frozen=True, slots=True)
class _Outgoing:
    source_node_id: str
    target_node_id: str
    certainties: tuple[GraphCertainty, ...]
    claims: tuple[MappingClaim, ...]
    derived_from_rule: bool
    conditional: bool
    conflict: bool


class MembershipGraphService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def build(self) -> GraphSnapshot:
        return self._build_state().snapshot

    def candidate_mapping_layer(self) -> MembershipMappingLayer:
        """Return non-official candidate/conflict claims without changing the main graph."""
        return self._third_party_layer(
            {MappingClaimStatus.CANDIDATE, MappingClaimStatus.CONFLICTING},
            traversable=False,
        )

    def approved_mapping_layer(self) -> MembershipMappingLayer:
        """Return the explicit, traversable approved third-party relation layer."""
        return self._third_party_layer(
            {MappingClaimStatus.APPROVED}, traversable=True
        )

    def _third_party_layer(
        self,
        statuses: set[MappingClaimStatus],
        *,
        traversable: bool,
    ) -> MembershipMappingLayer:
        claims: list[MembershipMappingClaim] = []
        for supplement in self._session.scalars(
            select(StatusMatchArticleSupplement).order_by(
                StatusMatchArticleSupplement.created_at,
                StatusMatchArticleSupplement.id,
            )
        ):
            claims.extend(
                claim
                for raw in supplement.mapping_claims
                if (claim := MembershipMappingClaim.model_validate(raw)).status
                in statuses
            )
        return MembershipMappingLayer(
            official=False,
            traversable=traversable,
            claims=claims,
        )

    def tree(
        self,
        program: str,
        tier: str,
        *,
        limits: TraversalLimits | None = None,
    ) -> MembershipTree:
        state = self._build_state()
        root = self._query_node(state, program, tier)
        return self._tree_from_root(state, root, limits or TraversalLimits())

    def audit(self) -> GraphAuditReport:
        state = self._build_state()
        snapshot = state.snapshot
        represented = [
            claim.id
            for edge in snapshot.edges
            for claim in edge.claims
        ] + [
            claim.id
            for rule in snapshot.rules
            for claim in rule.claims
        ]
        represented_counts = Counter(represented)
        expected = set(snapshot.expected_claim_ids)
        represented_set = set(represented)
        represented_claims = {
            claim.id: claim
            for edge in snapshot.edges
            for claim in edge.claims
        }
        represented_claims.update(
            {
                claim.id: claim
                for rule in snapshot.rules
                for claim in rule.claims
            }
        )
        material_mismatches, direction_mismatches, missing_evidence = (
            self._audit_claim_materials(state, represented_claims)
        )
        fidelity = ClaimFidelityAudit(
            expected_claim_count=len(expected),
            represented_claim_count=len(represented_set),
            missing_claim_ids=sorted(expected - represented_set),
            invented_claim_ids=sorted(represented_set - expected),
            duplicate_claim_ids=sorted(
                claim_id
                for claim_id, count in represented_counts.items()
                if count > 1
            ),
            material_mismatch_claim_ids=material_mismatches,
            direction_mismatch_claim_ids=direction_mismatches,
            missing_evidence_claim_ids=missing_evidence,
            unavailable_mapping_count=snapshot.unavailable_mapping_count,
        )

        self_loops = sorted(
            edge.id
            for edge in snapshot.edges
            if edge.source_node_id == edge.target_node_id
        )
        components = _strongly_connected_components(snapshot.nodes, snapshot.edges)
        source_counts = Counter(edge.source_node_id for edge in snapshot.edges)
        representative_ids = [
            node_id
            for node_id, _count in sorted(
                source_counts.items(), key=lambda item: (-item[1], item[0])
            )[:5]
        ]
        representative_trees = [
            self._tree_from_root(
                state,
                state.nodes[node_id],
                TraversalLimits(max_depth=6, max_nodes=250, max_branches=30),
            )
            for node_id in representative_ids
        ]
        topology = GraphTopologyAudit(
            program_count=len(snapshot.programs),
            node_count=len(snapshot.nodes),
            edge_count=len(snapshot.edges),
            rule_count=len(snapshot.rules),
            self_loop_edge_ids=self_loops,
            strongly_connected_components=components,
            conditional_edge_count=sum(edge.conditional for edge in snapshot.edges),
            conflicting_edge_count=sum(edge.conflict for edge in snapshot.edges),
            wildcard_rule_count=sum(
                rule.certainty == GraphCertainty.WILDCARD
                for rule in snapshot.rules
            ),
            uncertain_rule_count=sum(
                rule.certainty == GraphCertainty.UNCERTAIN
                for rule in snapshot.rules
            ),
            alias_ambiguities=snapshot.alias_ambiguities,
            representative_roots=representative_ids,
            representative_cycle_count=sum(tree.cycle_count for tree in representative_trees),
            representative_cross_reference_count=sum(
                tree.cross_reference_count for tree in representative_trees
            ),
            representative_truncated_count=sum(
                tree.truncated_count for tree in representative_trees
            ),
        )
        return GraphAuditReport(
            watch_ids=snapshot.watch_ids,
            event_ids=snapshot.event_ids,
            fact_set_ids=snapshot.fact_set_ids,
            fidelity=fidelity,
            topology=topology,
        )

    def _audit_claim_materials(
        self,
        state: _GraphState,
        represented_claims: dict[str, MappingClaim],
    ) -> tuple[list[str], list[str], list[str]]:
        edge_by_claim = {
            claim.id: edge
            for edge in state.snapshot.edges
            for claim in edge.claims
        }
        rule_by_claim = {
            claim.id: rule
            for rule in state.snapshot.rules
            for claim in rule.claims
        }
        material_mismatches: list[str] = []
        direction_mismatches: list[str] = []
        missing_evidence: list[str] = []
        records: dict[UUID, FactSet] = {}
        for claim_id in state.snapshot.expected_claim_ids:
            claim = represented_claims.get(claim_id)
            if claim is None:
                continue
            if not claim.evidence:
                missing_evidence.append(claim_id)
            record_facts = records.get(claim.fact_set_id)
            if record_facts is None:
                record = self._session.get(FactSetRecord, claim.fact_set_id)
                if record is None:
                    material_mismatches.append(claim_id)
                    continue
                record_facts = FactSet.model_validate(record.facts)
                records[claim.fact_set_id] = record_facts
            try:
                _fact_id, mapping_index, tier_index = claim_id.rsplit(":", 2)
                mapping = record_facts.status_mappings[int(mapping_index)]
                source_tier = mapping.source_tiers[int(tier_index)]
            except (IndexError, ValueError):
                material_mismatches.append(claim_id)
                continue
            if not _claim_matches_fact(claim, mapping, source_tier):
                material_mismatches.append(claim_id)

            edge = edge_by_claim.get(claim_id)
            if edge is not None:
                source = state.nodes[edge.source_node_id]
                target = state.nodes[edge.target_node_id]
                expected_source_alias = _display_text(
                    f"{mapping.source_program} {source_tier}"
                )
                expected_target_alias = _display_text(mapping.target_tier)
                if (
                    expected_source_alias not in source.aliases
                    or expected_target_alias not in target.aliases
                ):
                    direction_mismatches.append(claim_id)
                continue
            rule = rule_by_claim.get(claim_id)
            if rule is None:
                direction_mismatches.append(claim_id)
                continue
            target = state.nodes[rule.target_node_id]
            if _display_text(mapping.target_tier) not in target.aliases:
                direction_mismatches.append(claim_id)
        return (
            sorted(set(material_mismatches)),
            sorted(set(direction_mismatches)),
            sorted(set(missing_evidence)),
        )

    def _build_state(self) -> _GraphState:
        rows = self._current_projects()
        registry = _ProgramRegistry()
        identities: dict[UUID, _TargetIdentity] = {}
        facts_by_event: dict[UUID, FactSet] = {}
        for _watch, event, record, _faq in rows:
            facts = FactSet.model_validate(record.facts)
            facts_by_event[event.id] = facts
            identities[event.id] = registry.add_target(
                event.program,
                (mapping.target_tier for mapping in facts.status_mappings),
            )
            registry.add_category(
                identities[event.id].program_key,
                _target_program_category(event.program),
            )

        raw_categories: dict[str, set[ProgramCategory]] = defaultdict(set)
        for _watch, _event, _record, faq in rows:
            for metadata in extract_statusmatch_mapping_source_metadata(
                raw_html=faq.raw_body,
                canonical_url=faq.canonical_url,
            ):
                raw_categories[_normalize_key(metadata.source_program)].add(
                    _program_category(metadata.category)
                )
        for raw_program, categories in raw_categories.items():
            program_key = registry.resolve(raw_program)
            for category in categories:
                registry.add_category(program_key, category)

        node_records: dict[str, _NodeRecord] = {}
        edge_claims: dict[tuple[str, str], list[MappingClaim]] = defaultdict(list)
        rule_claims: dict[
            tuple[str | None, ProgramCategory, str | None, str, GraphCertainty],
            list[MappingClaim],
        ] = defaultdict(list)
        expected_claim_ids: list[str] = []
        unavailable_mapping_count = 0

        for watch, event, record, _faq in rows:
            facts = facts_by_event[event.id]
            identity = identities[event.id]
            target_program = registry.records[identity.program_key]
            for mapping_index, mapping in enumerate(facts.status_mappings):
                if mapping.availability == MappingAvailability.UNAVAILABLE:
                    unavailable_mapping_count += 1
                    continue
                target_node_id = self._ensure_node(
                    registry,
                    node_records,
                    identity.program_key,
                    _target_tier(mapping.target_tier, identity.aliases),
                    raw_alias=mapping.target_tier,
                )
                source_category = _single_category(
                    raw_categories.get(_normalize_key(mapping.source_program), set())
                )
                wildcard_program_category = _wildcard_program_category(
                    mapping.source_program, source_category
                )
                source_program_is_wildcard = (
                    wildcard_program_category != ProgramCategory.UNKNOWN
                    and _WILDCARD_PROGRAM_RE.search(mapping.source_program) is not None
                )
                source_program_key = (
                    None
                    if source_program_is_wildcard
                    else registry.resolve(mapping.source_program)
                )
                if source_program_key is not None:
                    registry.add_category(source_program_key, source_category)
                for tier_index, source_tier in enumerate(mapping.source_tiers):
                    claim_id = f"{record.id}:{mapping_index}:{tier_index}"
                    expected_claim_ids.append(claim_id)
                    claim = MappingClaim(
                        id=claim_id,
                        watch_id=watch.id,
                        host=watch.host,
                        event_id=event.id,
                        fact_set_id=record.id,
                        source_program=mapping.source_program,
                        source_tier=source_tier,
                        target_program=target_program.label,
                        target_tier=mapping.target_tier,
                        source_category=source_category,
                        availability=mapping.availability,
                        conditions=mapping.conditions,
                        evidence=mapping.evidence,
                        conflict=mapping.conflict,
                        conflict_note=mapping.conflict_note,
                    )
                    tier_kind = _tier_kind(source_tier)
                    if source_program_is_wildcard or tier_kind != GraphCertainty.EXACT:
                        certainty = (
                            GraphCertainty.UNCERTAIN
                            if tier_kind == GraphCertainty.UNCERTAIN
                            else GraphCertainty.WILDCARD
                        )
                        rule_key = (
                            source_program_key,
                            wildcard_program_category,
                            (
                                _normalize_tier(source_tier)
                                if tier_kind == GraphCertainty.EXACT
                                else None
                            ),
                            target_node_id,
                            certainty,
                        )
                        rule_claims[rule_key].append(claim)
                        continue
                    assert source_program_key is not None
                    source_node_id = self._ensure_node(
                        registry,
                        node_records,
                        source_program_key,
                        source_tier,
                        raw_alias=f"{mapping.source_program} {source_tier}",
                    )
                    edge_claims[(source_node_id, target_node_id)].append(claim)

        nodes = {
            node_id: MembershipNode(
                id=node.id,
                program_key=node.program_key,
                tier_key=node.tier_key,
                program=node.program,
                tier=node.tier,
                aliases=sorted(node.aliases, key=str.casefold),
                categories=sorted(
                    registry.records[node.program_key].categories, key=str
                ),
            )
            for node_id, node in node_records.items()
        }
        edges = [
            _membership_edge(source, target, claims)
            for (source, target), claims in edge_claims.items()
        ]
        edges.sort(key=lambda item: (item.source_node_id, item.target_node_id))
        rules = [
            _membership_rule(key, claims)
            for key, claims in rule_claims.items()
        ]
        rules.sort(key=lambda item: item.id)
        snapshot = GraphSnapshot(
            watch_ids=[watch.id for watch, _event, _record, _faq in rows],
            event_ids=[event.id for _watch, event, _record, _faq in rows],
            fact_set_ids=[record.id for _watch, _event, record, _faq in rows],
            programs=registry.programs(),
            nodes=sorted(nodes.values(), key=lambda item: item.id),
            edges=edges,
            rules=rules,
            expected_claim_ids=sorted(expected_claim_ids),
            unavailable_mapping_count=unavailable_mapping_count,
            alias_ambiguities=registry.ambiguity_models(),
        )
        edges_by_source: dict[str, list[MembershipEdge]] = defaultdict(list)
        for edge in edges:
            edges_by_source[edge.source_node_id].append(edge)
        return _GraphState(
            snapshot=snapshot,
            registry=registry,
            identities=identities,
            nodes=nodes,
            edges_by_source=dict(edges_by_source),
            rules=rules,
        )

    def _current_projects(
        self,
    ) -> list[tuple[StatusMatchWatch, StatusEvent, FactSetRecord, DocumentVersion]]:
        result: list[
            tuple[StatusMatchWatch, StatusEvent, FactSetRecord, DocumentVersion]
        ] = []
        watches = self._session.scalars(
            select(StatusMatchWatch)
            .where(StatusMatchWatch.status == "ACTIVE")
            .order_by(StatusMatchWatch.host)
        )
        for watch in watches:
            if watch.current_event_id is None:
                continue
            event = self._session.get(StatusEvent, watch.current_event_id)
            if (
                event is None
                or event.current_fact_set_id is None
                or event.archived_at is not None
                or event.merged_into_id is not None
            ):
                continue
            record = self._session.get(FactSetRecord, event.current_fact_set_id)
            faq_page = self._session.scalar(
                select(StatusMatchWatchPage).where(
                    StatusMatchWatchPage.watch_id == watch.id,
                    StatusMatchWatchPage.page_kind == "faq",
                    StatusMatchWatchPage.current_document_version_id.is_not(None),
                )
            )
            faq = (
                self._session.get(DocumentVersion, faq_page.current_document_version_id)
                if faq_page is not None
                else None
            )
            if record is not None and faq is not None:
                result.append((watch, event, record, faq))
        return result

    @staticmethod
    def _ensure_node(
        registry: _ProgramRegistry,
        nodes: dict[str, _NodeRecord],
        program_key: str,
        tier: str,
        *,
        raw_alias: str,
    ) -> str:
        tier_label = _display_tier(tier)
        tier_key = _normalize_tier(tier_label)
        node_id = f"{program_key}::{tier_key}"
        program = registry.records[program_key]
        node = nodes.setdefault(
            node_id,
            _NodeRecord(
                id=node_id,
                program_key=program_key,
                tier_key=tier_key,
                program=program.label,
                tier=tier_label,
            ),
        )
        node.aliases.add(_display_text(raw_alias))
        return node_id

    def _query_node(
        self,
        state: _GraphState,
        program: str,
        tier: str,
    ) -> MembershipNode:
        program_key = state.registry.resolve(program)
        record = state.registry.records[program_key]
        tier_label = _display_tier(tier)
        node_id = f"{program_key}::{_normalize_tier(tier_label)}"
        existing = state.nodes.get(node_id)
        if existing is not None:
            return existing
        return MembershipNode(
            id=node_id,
            program_key=program_key,
            tier_key=_normalize_tier(tier_label),
            program=record.label,
            tier=tier_label,
            aliases=[_display_text(f"{program} {tier}")],
            categories=sorted(record.categories, key=str),
        )

    def _tree_from_root(
        self,
        state: _GraphState,
        root: MembershipNode,
        limits: TraversalLimits,
    ) -> MembershipTree:
        counters = _TreeCounters()
        expanded: set[str] = set()
        root_tree = self._expand_node(
            state,
            root,
            depth=0,
            ancestors={root.id},
            expanded=expanded,
            counters=counters,
            limits=limits,
        )
        return MembershipTree(
            root=root_tree,
            limits=limits,
            occurrence_count=counters.occurrences,
            expanded_node_count=counters.expanded,
            cycle_count=counters.cycles,
            cross_reference_count=counters.cross_references,
            truncated_count=counters.truncated,
        )

    def _expand_node(
        self,
        state: _GraphState,
        node: MembershipNode,
        *,
        depth: int,
        ancestors: set[str],
        expanded: set[str],
        counters: _TreeCounters,
        limits: TraversalLimits,
    ) -> MembershipTreeNode:
        outgoing = self._outgoing(state, node)
        if not outgoing:
            expanded.add(node.id)
            return MembershipTreeNode(node=node, state=TreeNodeState.LEAF)
        if depth >= limits.max_depth:
            counters.truncated += len(outgoing)
            return MembershipTreeNode(
                node=node,
                state=TreeNodeState.DEPTH_LIMIT,
                omitted_count=len(outgoing),
            )

        expanded.add(node.id)
        counters.expanded += 1
        selected = outgoing[: limits.max_branches]
        branch_omitted = len(outgoing) - len(selected)
        if branch_omitted:
            counters.truncated += branch_omitted
        children: list[MembershipTreeEdge] = []
        node_limit_omitted = 0
        for index, outgoing_edge in enumerate(selected):
            if counters.occurrences >= limits.max_nodes:
                node_limit_omitted = len(selected) - index
                counters.truncated += node_limit_omitted
                break
            target = state.nodes[outgoing_edge.target_node_id]
            counters.occurrences += 1
            if target.id in ancestors:
                counters.cycles += 1
                child = MembershipTreeNode(node=target, state=TreeNodeState.CYCLE)
            elif target.id in expanded:
                counters.cross_references += 1
                child = MembershipTreeNode(
                    node=target,
                    state=TreeNodeState.CROSS_REFERENCE,
                )
            else:
                child = self._expand_node(
                    state,
                    target,
                    depth=depth + 1,
                    ancestors={*ancestors, target.id},
                    expanded=expanded,
                    counters=counters,
                    limits=limits,
                )
            children.append(
                MembershipTreeEdge(
                    source_node_id=node.id,
                    target_node_id=target.id,
                    certainties=list(outgoing_edge.certainties),
                    claims=list(outgoing_edge.claims),
                    derived_from_rule=outgoing_edge.derived_from_rule,
                    conditional=outgoing_edge.conditional,
                    conflict=outgoing_edge.conflict,
                    child=child,
                )
            )

        if node_limit_omitted:
            state_value = TreeNodeState.NODE_LIMIT
            omitted = branch_omitted + node_limit_omitted
        elif branch_omitted:
            state_value = TreeNodeState.BRANCH_LIMIT
            omitted = branch_omitted
        else:
            state_value = TreeNodeState.EXPANDED
            omitted = 0
        return MembershipTreeNode(
            node=node,
            state=state_value,
            children=children,
            omitted_count=omitted,
        )

    @staticmethod
    def _outgoing(state: _GraphState, node: MembershipNode) -> list[_Outgoing]:
        grouped: dict[str, dict[str, object]] = {}
        for edge in state.edges_by_source.get(node.id, []):
            grouped[edge.target_node_id] = {
                "certainties": set(edge.certainties),
                "claims": {claim.id: claim for claim in edge.claims},
                "derived": False,
                "conditional": edge.conditional,
                "conflict": edge.conflict,
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
                rule.target_node_id,
                {
                    "certainties": set(),
                    "claims": {},
                    "derived": False,
                    "conditional": False,
                    "conflict": False,
                },
            )
            certainties = item["certainties"]
            claims = item["claims"]
            assert isinstance(certainties, set)
            assert isinstance(claims, dict)
            certainties.add(rule.certainty)
            claims.update({claim.id: claim for claim in rule.claims})
            item["derived"] = True
            item["conditional"] = bool(item["conditional"]) or any(
                claim.availability == MappingAvailability.CONDITIONAL
                for claim in rule.claims
            )
            item["conflict"] = bool(item["conflict"]) or any(
                claim.conflict for claim in rule.claims
            )

        result: list[_Outgoing] = []
        for target_node_id, item in grouped.items():
            certainties = item["certainties"]
            claims = item["claims"]
            assert isinstance(certainties, set)
            assert isinstance(claims, dict)
            result.append(
                _Outgoing(
                    source_node_id=node.id,
                    target_node_id=target_node_id,
                    certainties=tuple(sorted(certainties, key=_certainty_rank)),
                    claims=tuple(sorted(claims.values(), key=lambda claim: claim.id)),
                    derived_from_rule=bool(item["derived"]),
                    conditional=bool(item["conditional"]),
                    conflict=bool(item["conflict"]),
                )
            )
        return sorted(
            result,
            key=lambda item: (
                state.nodes[item.target_node_id].program.casefold(),
                state.nodes[item.target_node_id].tier.casefold(),
                tuple(_certainty_rank(value) for value in item.certainties),
            ),
        )


def _membership_edge(
    source_node_id: str,
    target_node_id: str,
    claims: list[MappingClaim],
) -> MembershipEdge:
    ordered_claims = sorted(claims, key=lambda claim: claim.id)
    return MembershipEdge(
        id=_stable_id("edge", source_node_id, target_node_id),
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        certainties=[GraphCertainty.EXACT],
        claims=ordered_claims,
        conditional=any(
            claim.availability == MappingAvailability.CONDITIONAL
            for claim in ordered_claims
        ),
        conflict=any(claim.conflict for claim in ordered_claims),
    )


def _claim_matches_fact(
    claim: MappingClaim,
    mapping: StatusMapping,
    source_tier: str,
) -> bool:
    return (
        claim.source_program == mapping.source_program
        and claim.source_tier == source_tier
        and claim.target_tier == mapping.target_tier
        and claim.availability == mapping.availability
        and claim.conditions == mapping.conditions
        and claim.evidence == mapping.evidence
        and claim.conflict == mapping.conflict
        and claim.conflict_note == mapping.conflict_note
    )


def _membership_rule(
    key: tuple[str | None, ProgramCategory, str | None, str, GraphCertainty],
    claims: list[MappingClaim],
) -> MembershipRule:
    program_key, category, tier_key, target_node_id, certainty = key
    return MembershipRule(
        id=_stable_id(
            "rule",
            program_key or "*",
            category.value,
            tier_key or "*",
            target_node_id,
            certainty.value,
        ),
        source_program_key=program_key,
        source_category=category,
        source_tier_key=tier_key,
        target_node_id=target_node_id,
        certainty=certainty,
        claims=sorted(claims, key=lambda claim: claim.id),
    )


def _strongly_connected_components(
    nodes: list[MembershipNode],
    edges: list[MembershipEdge],
) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.source_node_id].append(edge.target_node_id)
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[list[str]] = []

    def visit(node_id: str) -> None:
        nonlocal index
        indices[node_id] = index
        lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)
        for target in adjacency.get(node_id, []):
            if target not in indices:
                visit(target)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
            elif target in on_stack:
                lowlinks[node_id] = min(lowlinks[node_id], indices[target])
        if lowlinks[node_id] != indices[node_id]:
            return
        component: list[str] = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node_id:
                break
        if len(component) > 1:
            result.append(sorted(component))

    for node in nodes:
        if node.id not in indices:
            visit(node.id)
    return sorted(result, key=lambda component: (len(component), component))


def _common_target_prefix(values: Iterable[str]) -> str | None:
    token_rows = [_display_text(value).split() for value in sorted(set(values))]
    if len(token_rows) < 2:
        return None
    normalized_rows = [[_normalize_key(token) for token in row] for row in token_rows]
    limit = min(len(row) for row in normalized_rows)
    length = 0
    while length < limit and len({row[length] for row in normalized_rows}) == 1:
        length += 1
    if length == 0 or any(len(row) == length for row in token_rows):
        return None
    return " ".join(token_rows[0][:length])


def _target_tier(value: str, aliases: Iterable[str]) -> str:
    raw_tokens = _display_text(value).split()
    normalized_tokens = [_normalize_key(token) for token in raw_tokens]
    for alias in sorted(aliases, key=lambda item: -len(_normalize_key(item).split())):
        alias_tokens = _normalize_key(alias).split()
        if normalized_tokens[: len(alias_tokens)] == alias_tokens:
            remaining = raw_tokens[len(alias_tokens) :]
            if remaining:
                return " ".join(remaining)
    return _display_text(value)


def _tier_kind(value: str) -> GraphCertainty:
    normalized = _normalize_key(value)
    if normalized in _UNCERTAIN_TIER_VALUES:
        return GraphCertainty.UNCERTAIN
    if _WILDCARD_TIER_RE.search(value) is not None:
        return GraphCertainty.WILDCARD
    return GraphCertainty.EXACT


def _wildcard_program_category(
    value: str,
    metadata_category: ProgramCategory,
) -> ProgramCategory:
    if _WILDCARD_PROGRAM_RE.search(value) is None:
        return ProgramCategory.UNKNOWN
    if metadata_category != ProgramCategory.UNKNOWN:
        return metadata_category
    folded = _normalize_key(value)
    if "airline" in folded:
        return ProgramCategory.AIRLINE
    if "hotel" in folded:
        return ProgramCategory.HOTEL
    if "cruise" in folded:
        return ProgramCategory.CRUISE
    if "card" in folded:
        return ProgramCategory.CARD
    return ProgramCategory.UNKNOWN


def _program_category(value: MappingSourceCategory) -> ProgramCategory:
    return ProgramCategory(value.value)


def _target_program_category(value: str) -> ProgramCategory:
    tokens = set(_normalize_key(value).split())
    if tokens & {"air", "airline", "airlines", "airways", "航空"}:
        return ProgramCategory.AIRLINE
    if tokens & {"hotel", "hotels", "hospitality", "酒店"}:
        return ProgramCategory.HOTEL
    if tokens & {"cruise", "cruises", "邮轮"}:
        return ProgramCategory.CRUISE
    return ProgramCategory.UNKNOWN


def _single_category(values: set[ProgramCategory]) -> ProgramCategory:
    concrete = {value for value in values if value != ProgramCategory.UNKNOWN}
    return next(iter(concrete)) if len(concrete) == 1 else ProgramCategory.UNKNOWN


def _distinctive_alias(tokens: list[str]) -> bool:
    return len(tokens) >= 2 or (len(tokens) == 1 and len(tokens[0]) >= 6)


def _display_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value).strip()


def _display_tier(value: str) -> str:
    displayed = _display_text(value)
    tokens = displayed.split()
    if len(tokens) > 1 and tokens[-1].casefold() == "status":
        displayed = " ".join(tokens[:-1])
    return displayed or "UNCERTAIN"


def _normalize_key(value: str) -> str:
    return _SPACE_RE.sub(" ", _NON_WORD_RE.sub(" ", value).casefold()).strip()


def _normalize_tier(value: str) -> str:
    normalized = _normalize_key(value)
    tokens = normalized.split()
    if len(tokens) > 1 and tokens[-1] == "status":
        normalized = " ".join(tokens[:-1])
    return normalized or "uncertain"


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("\x1f".join(values).encode()).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _certainty_rank(value: GraphCertainty) -> int:
    return {
        GraphCertainty.EXACT: 0,
        GraphCertainty.WILDCARD: 1,
        GraphCertainty.UNCERTAIN: 2,
    }[value]
