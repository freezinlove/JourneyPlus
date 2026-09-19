"""Append terminal, explicitly uncertain opportunities after exact graph traversal."""
from journeyplus.contracts import FactSet
from journeyplus.lifecycle.visibility import contributes
from journeyplus.membership.identity import canonical_program, canonical_tier
from journeyplus.membership.normalization import normalize_key, normalize_tier
from journeyplus.models import StatusEvent, FactSetRecord
from .publication import signature


def append_opportunities(session, state, roots, query, result, programs):
    from .workflow_knowledge import WorkflowActivityReader, identity_id, brief_url
    from .workflow_routes import matching_paid
    if not roots:
        return
    count = 0
    for activity in WorkflowActivityReader(session).locate(limit=100000):
        if not contributes(activity):
            continue
        record = session.get(FactSetRecord, activity.current_fact_set_id) if isinstance(activity, StatusEvent) else activity
        if not record or not record.facts.get('matching_opportunities'):
            continue
        facts = FactSet.model_validate(record.facts)
        if str(facts.opportunity_kind) != "STATUS_MATCH":
            continue
        target_program = canonical_program(activity.program)
        target_key = normalize_key(target_program)
        pid = identity_id('program', target_key)
        program = programs.get(pid)
        if query.target_program_id and query.target_program_id != pid:
            continue
        if query.category and (program is None or query.category != program.category):
            continue
        if query.alliance and (program is None or query.alliance != program.alliance):
            continue
        version = record.id if isinstance(activity, StatusEvent) else activity.analysis_id
        for index, opportunity in enumerate(facts.matching_opportunities):
            targets = list(dict.fromkeys(canonical_tier(target_program, t) for t in opportunity.possible_target_tiers))
            if query.target_tier_id and query.target_tier_id not in {
                identity_id('tier', target_key+'::'+normalize_tier(t)) for t in targets
            }:
                continue
            source_key = normalize_key(canonical_program(opportunity.source_program))
            allowed = {normalize_tier(canonical_tier(opportunity.source_program, t)) for t in opportunity.source_tiers}
            fees = [matching_paid(facts, t, program_aliases=(target_program,)) for t in targets]
            paid = fees[0] if fees and all(f is fees[0] for f in fees) else None
            if query.free_only and paid is not False:
                continue
            for root in roots:
                source = state.nodes[root]
                if normalize_key(canonical_program(source.program)) != source_key or allowed and source.tier_key not in allowed:
                    continue
                # No guessed membership node is inserted into the traversable graph.
                sid = signature(['possible-match', root, str(activity.id), str(version), index])[:24]
                target_id = 'opportunity:'+signature([str(activity.id), str(version), index])[:24]
                note = '可能适用；具体等级待确认。来源资格：'+opportunity.source_qualification
                if opportunity.conditions:
                    note += '；'+opportunity.conditions
                step = dict(ref=sid, **{'from': source.program+' '+source.tier, 'to': target_program+'（可能获得：'+' 或 '.join(targets)+'）'},
                    from_tier_id=str(identity_id('tier', root)), to_tier_id=target_id,
                    activity_ref=str(activity.id), version_ref=str(version), mapping_ref=f'opportunity-{index}',
                    mapping_status='UNCONFIRMED', certainty='UNKNOWN', availability='UNKNOWN', terminal=True,
                    target_program_name=target_program, target_program_id=str(pid),
                    possible_target_tiers=targets, source_qualification=opportunity.source_qualification,
                    conditions=opportunity.conditions, uncertainty_note=note,
                    paid=paid, fee_status='UNKNOWN' if paid is None else 'PAID' if paid else 'FREE',
                    fact_refs=[f'activity:{activity.id}@{version}'], brief_url=brief_url(activity.id, version))
                result['server_steps'][sid] = step
                ref = signature(['possible-route', sid])[:16]
                result['server_routes'][ref] = dict(ref=ref, **{'from':step['from'], 'to':step['to']},
                    step_refs=[sid], step_count=1, paid=paid, fee_status=step['fee_status'],
                    classification='UNKNOWN', mapping_status='UNCONFIRMED', terminal=True,
                    uncertainty_note=note, fact_refs=step['fact_refs'])
                result['snapshot'][str(activity.id)] = str(version)
                count += 1
    result['coverage']['unconfirmed_opportunity_count'] = count
    if count:
        result['presentation_classes'].append('UNKNOWN')
        result['coverage']['scope_description'] += ' 另含从当前起点出发的待确认机会，非确定等级映射，不参与后续路径计算。'
