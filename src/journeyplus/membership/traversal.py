from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar


RelationT = TypeVar("RelationT")
NodeTreeT = TypeVar("NodeTreeT")
EdgeTreeT = TypeVar("EdgeTreeT")


class TraversalLimitsLike(Protocol):
    max_depth: int
    max_nodes: int
    max_branches: int


@dataclass(slots=True)
class TraversalCounters:
    occurrences: int = 1
    expanded: int = 0
    cycles: int = 0
    cross_references: int = 0
    truncated: int = 0


def expand_bounded_tree(
    node_id: str,
    *,
    depth: int,
    ancestors: set[str],
    expanded: set[str],
    counters: TraversalCounters,
    limits: TraversalLimitsLike,
    outgoing: Callable[[str], Sequence[RelationT]],
    target_id: Callable[[RelationT], str],
    make_node: Callable[[str, str, list[EdgeTreeT], int], NodeTreeT],
    make_edge: Callable[[str, str, RelationT, NodeTreeT], EdgeTreeT],
) -> NodeTreeT:
    """Expand direct adjacency with shared cycle, cross-reference and limit rules."""

    relations = list(outgoing(node_id))
    if not relations:
        expanded.add(node_id)
        return make_node(node_id, "LEAF", [], 0)
    if depth >= limits.max_depth:
        counters.truncated += len(relations)
        return make_node(node_id, "DEPTH_LIMIT", [], len(relations))

    expanded.add(node_id)
    counters.expanded += 1
    selected = relations[: limits.max_branches]
    branch_omitted = len(relations) - len(selected)
    counters.truncated += branch_omitted
    children: list[EdgeTreeT] = []
    node_limit_omitted = 0
    for index, relation in enumerate(selected):
        if counters.occurrences >= limits.max_nodes:
            node_limit_omitted = len(selected) - index
            counters.truncated += node_limit_omitted
            break
        child_id = target_id(relation)
        counters.occurrences += 1
        if child_id in ancestors:
            counters.cycles += 1
            child = make_node(child_id, "CYCLE", [], 0)
        elif child_id in expanded:
            counters.cross_references += 1
            child = make_node(child_id, "CROSS_REFERENCE", [], 0)
        else:
            child = expand_bounded_tree(
                child_id,
                depth=depth + 1,
                ancestors={*ancestors, child_id},
                expanded=expanded,
                counters=counters,
                limits=limits,
                outgoing=outgoing,
                target_id=target_id,
                make_node=make_node,
                make_edge=make_edge,
            )
        children.append(make_edge(node_id, child_id, relation, child))

    if node_limit_omitted:
        state = "NODE_LIMIT"
        omitted = branch_omitted + node_limit_omitted
    elif branch_omitted:
        state = "BRANCH_LIMIT"
        omitted = branch_omitted
    else:
        state = "EXPANDED"
        omitted = 0
    return make_node(node_id, state, children, omitted)
