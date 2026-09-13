"""Read current workflow mappings into the shared simple matching graph."""
from datetime import UTC, datetime
from journeyplus.knowledge.publication import signature
from journeyplus.membership.unified import _outgoing
from journeyplus.membership.normalization import stable_id
from journeyplus.product.opportunities import PersonalizedMatchService
from journeyplus.fee_policy import route_fees
from .workflow_knowledge import catalog, graph_state, identity_id, brief_url
from .simple_matching import shortest_graph, POLICY


def mapping_ref(claim, facts):
    for index, mapping in enumerate(facts.status_mappings):
        for tier_index, _ in enumerate(mapping.source_tiers):
            expected = (f'official:{claim.provenance.fact_set_id}:{index}:{tier_index}'
                if claim.provenance.fact_set_id else stable_id('article-contribution',
                    str(claim.provenance.opportunity_id), str(index), str(tier_index)))
            if expected == claim.contribution_id:
                return f'mapping-{index}'
    raise ValueError('Graph contribution cannot be located in its FactSet version')


def matching_paid(facts, target_tier):
    """Binary mandatory payment only. Region and amount never become branches."""
    for option in facts.application_routes or [None]:
        policy = route_fees(facts, option, target_tier=target_tier)
        if 'PAID' in policy.states or any(p.amount is not None and p.amount > 0
                and p.availability not in {'CONDITIONAL', 'UNAVAILABLE'} for _, p in policy.prices):
            return True
    return False


class WorkflowRouteService:
    def __init__(self, session, *, holding_snapshot=None, state=None):
        self.session = session
        self.state = state
        self.holding_snapshot = holding_snapshot or []

    def query(self, query, *, shortlist=8, max_states=10000, max_edges=20000, deadline_seconds=2):
        state = self.state if self.state is not None else graph_state(self.session)
        programs, _, _ = catalog(self.session, state=state)
        programs = {p.id: p for p in programs}
        tier_nodes = {identity_id('tier', n.id): n for n in state.nodes.values()}
        roots = [tier_nodes[t].id for t in query.starting_tier_ids if t in tier_nodes]
        details = {}
        def outgoing(source):
            choices = {}
            for relation in _outgoing(state, state.nodes[source]):
                target = state.nodes[relation.target_node_id]
                for claim in relation.contributions:
                    if claim.availability == 'UNAVAILABLE':
                        continue
                    origin = claim.provenance
                    identity = origin.fact_set_id or origin.opportunity_id
                    if identity is None:
                        continue
                    if identity not in details:
                        details[identity] = PersonalizedMatchService(self.session)._facts_for_opportunity(identity)
                    facts = details[identity]
                    if facts is None:
                        continue
                    activity = origin.event_id or origin.opportunity_id
                    if origin.fact_set_id:
                        version = origin.fact_set_id
                    else:
                        from journeyplus.models import ArticleOpportunityRecord
                        version = self.session.get(ArticleOpportunityRecord, identity).analysis_id
                    paid = matching_paid(facts, target.tier_key)
                    pid = identity_id('program', target.program_key)
                    mapping = mapping_ref(claim, facts)
                    sid = signature([POLICY, source, target.id, str(activity), str(version), mapping])[:24]
                    step = {'ref': sid, 'matching_policy': POLICY, 'paid': paid, 'fee_free': not paid,
                        'activity_ref': str(activity), 'version_ref': str(version), 'mapping_ref': mapping,
                        'from_tier_id': str(identity_id('tier', source)), 'to_tier_id': str(identity_id('tier', target.id)),
                        'from': state.nodes[source].program+' '+state.nodes[source].tier,
                        'to': target.program+' '+target.tier, 'target_program_id': str(pid),
                        'target_category': programs[pid].category, 'target_alliance': str(target.alliance) if target.alliance else None,
                        'certainty': str(claim.certainty), 'derived_from_rule': relation.derived_from_rule,
                        'fact_refs': [f'activity:{activity}@{version}'], 'availability': str(claim.availability),
                        'brief_url': brief_url(activity, version)}
                    # One real supporting mapping per connection, free first.
                    old = choices.get(target.id)
                    if old is None or (paid, sid) < (old['paid'], old['ref']):
                        choices[target.id] = step
            return list(choices.items())
        def wanted(node_id):
            node = state.nodes[node_id]
            pid = identity_id('program', node.program_key)
            return ((query.target_program_id is None or query.target_program_id == pid)
                and (query.target_tier_id is None or query.target_tier_id == identity_id('tier', node_id))
                and (query.category is None or query.category == programs[pid].category)
                and (query.alliance is None or query.alliance == str(node.alliance)))
        result = shortest_graph(state.nodes, roots, outgoing, wanted, free_only=query.free_only,
            exact_tier=query.target_tier_id is not None, max_states=max_states, max_edges=max_edges,
            deadline_seconds=deadline_seconds)
        result['coverage'].update(excluded_contribution_count=len(state.excluded), unresolved_alliance_program_count=0)
        if not roots:
            result['coverage'].update(search_complete=False, searched_published_graph_complete=False,
                stopped_reason='SOURCE_IDENTITY_REQUIRED')
        return result


def matching_forest(session, root_ids, *, technical_node_limit=5000, now=None, state=None):
    """Adapt the same selected graph to existing personalized-page tree DTOs."""
    from journeyplus.membership.contracts import ReachableMembershipForest, ReachableMembershipTreeNode, ReachableMembershipTreeEdge
    from .simple_matching import MatchingQuery
    from uuid import UUID
    if state is None:
        from journeyplus.membership.unified import UnifiedMembershipTreeService
        state = UnifiedMembershipTreeService(session)._build_state(now=now)
    missing = set(root_ids)-state.nodes.keys()
    if missing:
        raise LookupError('Unknown membership nodes: '+', '.join(sorted(missing)))
    result = WorkflowRouteService(session, state=state).query(MatchingQuery(
        starting_tier_ids=[identity_id('tier', node) for node in root_ids]), max_states=technical_node_limit)
    node_ids = {str(identity_id('tier', node)): node for node in state.nodes}
    children = {}
    for step in result['server_steps'].values():
        source, target = node_ids[step['from_tier_id']], node_ids[step['to_tier_id']]
        children.setdefault(source, []).append((target, step))
    def tree(node):
        edges = []
        for target, step in sorted(children.get(node, [])):
            identity = UUID(step['version_ref']) if step['fact_refs'][0].startswith('activity:') else UUID(step['activity_ref'])
            from journeyplus.models import FactSetRecord
            if session.get(FactSetRecord, identity) is None:
                identity = UUID(step['activity_ref'])
            edges.append(ReachableMembershipTreeEdge(source_node_id=node, target_node_id=target,
                opportunity_ids=[identity], contribution_ids=[], certainties=[step['certainty']], derived_from_rule=step['derived_from_rule'], child=tree(target)))
        return ReachableMembershipTreeNode(node=state.nodes[node], state='EXPANDED' if edges else 'LEAF' if result['coverage']['search_complete'] else 'NODE_LIMIT', children=edges)
    nodes = set(root_ids)|{node_ids[step['to_tier_id']] for step in result['server_steps'].values()}
    return ReachableMembershipForest(roots=[tree(node) for node in sorted(set(root_ids))],
        technical_node_limit=technical_node_limit, occurrence_count=len(nodes), expanded_node_count=len(nodes),
        cycle_count=0, cross_reference_count=0, truncated_count=int(not result['coverage']['search_complete']))
