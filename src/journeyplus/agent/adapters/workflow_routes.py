"""Adapt existing workflow graph contributions to the Agent route result contract."""
from collections import deque
from datetime import UTC, datetime
from time import monotonic
import re

from journeyplus.knowledge.routes import RouteService
from journeyplus.knowledge.publication import signature
from journeyplus.knowledge.selection import order_candidates
from journeyplus.membership.unified import _outgoing
from journeyplus.membership.normalization import normalize_tier, stable_id
from journeyplus.product.opportunities import PersonalizedMatchService
from journeyplus.product.candidate_routes import _NO_CHALLENGE, _CHALLENGE
from .workflow_knowledge import catalog, graph_state, identity_id


def regional_applicability(region, residency):
    """Recognize explicit country lists only; prose and exclusions stay unknown."""
    if not region:
        return True
    if not residency:
        return None
    from journeyplus.knowledge.countries import _ALIASES, key, country_in
    countries = [part.strip() for part in re.split(r',|;|、|，|\s+and\s+|\s*&\s*',region,flags=re.I)]
    if not countries or any(key(country) not in _ALIASES for country in countries):
        return None
    return country_in(residency,countries)


def mapping_ref(claim, facts):
    """Resolve producer contribution IDs to the unchanged FactSet array index."""
    for index,mapping in enumerate(facts.status_mappings):
        for tier_index,_ in enumerate(mapping.source_tiers):
            expected = (f'official:{claim.provenance.fact_set_id}:{index}:{tier_index}'
                if claim.provenance.fact_set_id else stable_id('article-contribution',
                    str(claim.provenance.opportunity_id),str(index),str(tier_index)))
            if expected==claim.contribution_id:
                return f'mapping-{index}'
    raise ValueError('Graph contribution cannot be located in its FactSet version')


class WorkflowRouteService:
    def __init__(self, session, *, holding_snapshot=None):
        self.session = session
        self.holding_snapshot = holding_snapshot or []

    def query(self, query, *, shortlist=8, max_states=10000, max_edges=20000, deadline_seconds=2):
        started = monotonic()
        state = graph_state(self.session)
        programs, tiers, _ = catalog(self.session)
        programs = {p.id:p for p in programs}
        tier_nodes = {identity_id('tier',n.id):n for n in state.nodes.values()}
        roots = [tier_nodes[t].id for t in query.starting_tier_ids if t in tier_nodes]
        work = deque((n,[],frozenset({n})) for n in sorted(set(roots)))
        details, steps, routes, versions = {}, {}, [], {}
        states = edges = 0
        stopped = None
        unknown_metadata = set()
        seen_paths = set()
        summarizer = RouteService(self.session,holding_snapshot=self.holding_snapshot)
        while work:
            if states >= max_states or edges >= max_edges or monotonic()-started >= deadline_seconds:
                stopped = 'STATE_BUDGET' if states>=max_states else 'EDGE_BUDGET' if edges>=max_edges else 'TIME_BUDGET'
                break
            node, path, visited = work.popleft()
            states += 1
            for outgoing in _outgoing(state,state.nodes[node]):
                target = state.nodes[outgoing.target_node_id]
                if target.id in visited:
                    continue
                for claim in outgoing.contributions:
                    edges += 1
                    if edges > max_edges or monotonic()-started >= deadline_seconds:
                        stopped = 'EDGE_BUDGET' if edges>max_edges else 'TIME_BUDGET'
                        break
                    origin = claim.provenance
                    opportunity_id = origin.fact_set_id or origin.opportunity_id
                    if opportunity_id is None:
                        continue
                    if opportunity_id not in details:
                        details[opportunity_id] = PersonalizedMatchService(self.session).detail(opportunity_id,include_current_path=False)
                    detail = details[opportunity_id]
                    if detail.lifecycle_status in {'CLOSED','EXPIRED','ARCHIVED'} or claim.availability=='UNAVAILABLE':
                        continue
                    activity = origin.event_id or origin.opportunity_id
                    if origin.fact_set_id:
                        version = origin.fact_set_id
                    else:
                        from journeyplus.models import ArticleOpportunityRecord
                        version = self.session.get(ArticleOpportunityRecord,opportunity_id).analysis_id
                    versions[str(activity)] = str(version)
                    facts = detail.facts
                    from journeyplus.models import StatusEvent
                    event = self.session.get(StatusEvent,activity) if origin.event_id else None
                    now = datetime.now(UTC)
                    def utc(value):
                        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value
                    if event and (event.application_start_at and utc(event.application_start_at)>now or
                                  event.application_deadline_at and utc(event.application_deadline_at)<now):
                        continue
                    # Each regional application route is a distinct variant. Never
                    # minimize across regions or charge a different target tier's fee.
                    for index, option in enumerate(facts.application_routes or [None]):
                        applies = regional_applicability(option.region if option else None,query.residency)
                        if applies is False:
                            continue
                        eligible_prices = [(i,p) for i,p in enumerate(option.prices) if not p.target_tier or
                            normalize_tier(p.target_tier)==target.tier_key] if option else []
                        if eligible_prices and all(p.availability=='UNAVAILABLE' for _,p in eligible_prices):
                            continue
                        fees, conditional = [], []
                        for price_index, price in eligible_prices:
                            if price.availability=='UNAVAILABLE': continue
                            value = {'ref':f'{version}/route-{index}/price-{price_index}',
                                'amount':str(price.amount) if price.amount is not None else None,
                                'currency':price.currency,'role':'APPLICATION','raw_text':price.raw_text,
                                'conditions':[option.region] if option and option.region else []}
                            if (applies is True and len(eligible_prices)==1 and price.availability=='AVAILABLE'
                                    and price.amount is not None and not option.conflict):
                                fees.append(value)
                            else:
                                conditional.append({**value,'applicability':'UNKNOWN','reason':option.region or '价格适用条件待确认'})
                        texts = [facts.eligibility.value, facts.region.value, claim.conditions,
                                 option.eligibility if option else None, option.region if option else None]
                        checks = [{'topic':'ELIGIBILITY','result':'UNKNOWN','reason':v} for v in dict.fromkeys(texts) if v]
                        checks.append({'topic':'ELIGIBILITY','result':'UNKNOWN',
                            'reason':'原模型保留文字条件；匹配关系不等于个人申请资格已经核实。'})
                        challenge_text = facts.challenge_requirements.value or ''
                        negative = bool(_NO_CHALLENGE.search(challenge_text))
                        positive = bool(_CHALLENGE.search(_NO_CHALLENGE.sub('',challenge_text)))
                        challenge = ('UNKNOWN' if facts.challenge_requirements.conflict or negative and positive
                            else 'NONE' if negative else 'REQUIRED' if positive else 'UNKNOWN')
                        sid = signature([claim.contribution_id,node,target.id,index,path])[:24]
                        pref = identity_id('program',target.program_key)
                        category = programs[pref].category
                        steps[sid] = {'ref':sid,'activity_ref':str(activity),'version_ref':str(version),
                            'option_ref':'route-'+str(index) if option else None,'mapping_ref':mapping_ref(claim,facts),
                            'claim_ref':claim.contribution_id,
                            'from_tier_id':str(identity_id('tier',node)), 'to_tier_id':str(identity_id('tier',target.id)),
                            'from':state.nodes[node].program+' '+state.nodes[node].tier,
                            'to':target.program+' '+target.tier, 'target_category':category,
                            'target_program_id':str(pref),
                            'target_alliance':str(target.alliance) if target.alliance else None,
                            'fees':fees,'conditional_items':conditional,'alternative_items':[],
                            'fee_unknown':not bool(fees),'fee_conflict':bool(option and option.conflict or facts.cost.conflict),
                            'challenge':challenge,'eligibility':'UNKNOWN','constraint_checks':checks,
                            'source_acquisition':query.source_acquisition if not path else 'MATCHED',
                            'material_caveats':[c['reason'] for c in checks]+[v for v in
                                [facts.caveats.value,claim.conflict_note,option.conflict_note if option else None] if v],
                            'fact_refs':[f'activity:{activity}@{version}'], 'availability':'UNKNOWN' if claim.conflict or outgoing.derived_from_rule else str(claim.availability),
                            'application_window':{'start':facts.application_start.value,'end':facts.deadline.value},
                            'status_validity':facts.status_validity.model_dump(mode='json'),
                            'action_link':str(option.action_link) if option and option.action_link else facts.action_link.value,
                            'source_links':detail.source_links, 'application_scope':option.scope if option else None,
                            'cost_description':option.cost if option else facts.cost.value,
                            'brief_url':f'/opportunities/{opportunity_id}'}
                        next_path = [*path,sid]
                        if tuple(next_path) in seen_paths: continue
                        seen_paths.add(tuple(next_path))
                        candidate = summarizer._summarize(next_path,steps,query)
                        wanted = (query.target_program_id is None or pref==query.target_program_id) and (
                            query.target_tier_id is None or identity_id('tier',target.id)==query.target_tier_id)
                        if query.category and category=='OTHER' or query.alliance and not target.alliance:
                            unknown_metadata.add(target.program_key)
                        wanted = wanted and (query.category is None or category==query.category) and (
                            query.alliance is None or str(target.alliance)==query.alliance)
                        if wanted: routes.append(candidate)
                        if candidate['classification']!='EXCLUDED':
                            work.append((target.id,next_path,visited|{target.id}))
                    if stopped: break
                if stopped: break
            if stopped: break
        ordered, _ = order_candidates(routes,query.preferences)
        unmapped = len(state.excluded)
        complete = stopped is None and not unknown_metadata
        # A query without a source cannot explore wildcard/public eligibility
        # that the original schema does not encode as a named starting tier.
        if not roots:
            complete = False
            stopped = stopped or 'SOURCE_IDENTITY_REQUIRED'
        return {'presentation_classes':['MATCH','UNKNOWN'],'server_routes':{r['ref']:r for r in ordered},'server_steps':steps,'snapshot':versions,
            'coverage':{'search_complete':complete,'searched_published_graph_complete':complete,
                'stopped_reason':stopped or ('CATALOG_METADATA_GAPS' if unknown_metadata else None),
                'expanded_states':states,'checked_edges':edges,'excluded_contribution_count':unmapped,
                'unresolved_alliance_program_count':len(unknown_metadata),
                'scope_description':'当前 AIWorkflow 的官方与文章匹配关系；文字条件保留，个人资格未自动证明。',
                'knowledge_complete':False,'knowledge_gap_reason':'Unrecorded mappings and textual eligibility are not proof of absence.'}}
