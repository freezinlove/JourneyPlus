"""Small deterministic matching graph. Exploration state is never a result."""
from collections import deque, defaultdict
from time import monotonic
from journeyplus.membership.normalization import normalize_key, normalize_tier
from journeyplus.knowledge.publication import signature
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

POLICY = 'simple-matching-v1'


class MatchingQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    starting_tier_ids: list[UUID] = Field(default_factory=list)
    use_saved_holdings: bool | None = None
    target_program_id: UUID | None = None
    target_tier_id: UUID | None = None
    category: Literal['AIRLINE', 'HOTEL', 'CRUISE', 'OTHER'] | None = None
    alliance: str | None = None
    free_only: bool = False

# Only explicit, comparable program ladders. Unknown ladders are not guessed.
TIER_ORDERS = {
    'flying blue': ('SILVER', 'GOLD', 'PLATINUM', 'ULTIMATE'),
    'lotusmiles': ('SILVER', 'TITANIUM', 'GOLD', 'PLATINUM'),
    'asante rewards': ('SILVER ELITE', 'GOLD ELITE PLUS', 'PLATINUM ELITE PLUS'),
    'royal jordanian royal club': ('SILVER JAY', 'GOLD SPARROW', 'PLATINUM HAWK'),
    'air astana nomad club': ('SILVER', 'GOLD'),
    'malaysia airlines enrich': ('SILVER', 'GOLD', 'PLATINUM'),
    'garuda indonesia garudamiles': ('SILVER', 'GOLD', 'PLATINUM'),
    'club avolta': ('GOLD',),
    'british airways club': ('BRONZE', 'SILVER', 'GOLD', 'GOLD GUEST LIST', 'PREMIER'),
    'marriott bonvoy': ('SILVER ELITE', 'GOLD ELITE', 'PLATINUM ELITE', 'TITANIUM ELITE', 'AMBASSADOR ELITE'),
}


def highest_targets(nodes, targets):
    groups = defaultdict(list)
    for node in targets:
        groups[nodes[node].program_key].append(node)
    selected, unordered = [], []
    for program, ids in sorted(groups.items()):
        order = TIER_ORDERS.get(normalize_key(program), ())
        ranks = {normalize_tier(tier): index for index, tier in enumerate(order)}
        if len(ids) == 1:
            selected.extend(ids)
        elif all(nodes[node].tier_key in ranks for node in ids):
            selected.append(max(ids, key=lambda node: ranks[nodes[node].tier_key]))
        else:
            selected.extend(sorted(ids))
            unordered.append(program)
    return selected, unordered


def shortest_graph(nodes, roots, outgoing, wanted, *, free_only=False, exact_tier=False,
                   max_states=10000, max_edges=20000, deadline_seconds=2):
    """One shortest predecessor per identity, with deterministic free-first ties."""
    started = monotonic()
    roots = sorted(set(roots))
    queue = deque(roots)
    parents = {root: None for root in roots}
    depth = dict.fromkeys(roots, 0)
    targets = []
    states = edges = 0
    stopped = None
    while queue:
        if states >= max_states or monotonic()-started >= deadline_seconds:
            stopped = 'STATE_BUDGET' if states >= max_states else 'TIME_BUDGET'
            break
        source = queue.popleft()
        states += 1
        for target, step in sorted(outgoing(source), key=lambda item: (item[1]['paid'], item[0], item[1]['ref'])):
            edges += 1
            if edges > max_edges or monotonic()-started >= deadline_seconds:
                stopped = 'EDGE_BUDGET' if edges > max_edges else 'TIME_BUDGET'
                break
            if free_only and step['paid'] or target in parents:
                continue
            if len(parents) >= max_states:
                stopped = 'STATE_BUDGET'
                break
            parents[target] = (source, step)
            depth[target] = depth[source]+1
            if wanted(target):
                targets.append(target)
                if exact_tier:
                    # An explicit single tier is settled on first BFS arrival.
                    queue.clear()
                    break
            queue.append(target)
        if stopped or exact_tier and targets:
            break
    selected, unordered = (targets, []) if exact_tier else highest_targets(nodes, targets)
    paths = {}
    for target in selected:
        path, node = [], target
        while parents[node] is not None:
            source, step = parents[node]
            path.append(step)
            node = source
        paths[target] = list(reversed(path))
    # A reachable destination already visible along a longer selected route
    # needs no separate prefix result. Connections are still retained once.
    prefixes = {step['to_tier_id'] for path in paths.values() for step in path[:-1]}
    paths = {target: path for target, path in paths.items() if path[-1]['to_tier_id'] not in prefixes}
    routes, steps = {}, {}
    for target, path in sorted(paths.items()):
        for step in path:
            steps[step['ref']] = step
        ids = [step['ref'] for step in path]
        ref = signature([POLICY, ids])[:16]
        paid = any(step['paid'] for step in path)
        routes[ref] = {'ref': ref, 'from': path[0]['from'], 'to': path[-1]['to'],
            'step_refs': ids, 'step_count': len(ids), 'paid': paid,
            'cost': {'state': 'KNOWN', 'paid': paid, 'is_proven_free': not paid},
            'classification': 'MATCH', 'eligibility': 'UNKNOWN', 'challenge': 'UNKNOWN',
            'fact_refs': list(dict.fromkeys(ref for step in path for ref in step['fact_refs']))}
    return {'matching_policy': POLICY, 'presentation_classes': ['MATCH'],
        'server_routes': routes, 'server_steps': steps,
        'snapshot': {step['activity_ref']: step['version_ref'] for step in steps.values()},
        'coverage': {'search_complete': stopped is None, 'searched_published_graph_complete': stopped is None,
            'stopped_reason': stopped, 'expanded_states': states, 'checked_edges': edges,
            'tier_order_unknown': unordered, 'knowledge_complete': False,
            'scope_description': '当前已记录会籍映射的最高目标等级最短路径；仅按免费/付费筛选，地区和金额见活动详情。'}}
