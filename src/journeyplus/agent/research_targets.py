"""Derive research identity from disclosed, version-bound route steps."""
import re
from uuid import UUID
from journeyplus.knowledge.models import ApplicationOptionVersion,ActivityKnowledgeVersion,Activity,MembershipTier,OptionMapping
from journeyplus.agent.step_observations import ResearchTarget


def resolve_research_targets(session,state,step_refs,*,refresh=False):
    targets=[]
    for ref in dict.fromkeys(step_refs):
        step=state.get('steps',{}).get(ref) or state.get('direct_research_steps',{}).get(ref)
        if step is None:raise ValueError('RESEARCH_STEP_NOT_DISCLOSED')
        option=session.get(ApplicationOptionVersion,UUID(step['option_ref']))
        version=session.get(ActivityKnowledgeVersion,UUID(step['version_ref']))
        mapping=session.get(OptionMapping,UUID(step['mapping_ref']))
        if option is None or version is None or mapping is None or option.knowledge_version_id!=version.id or mapping.option_version_id!=option.id:
            raise ValueError('RESEARCH_STEP_VERSION_MISMATCH')
        activity=session.get(Activity,version.activity_id)
        if refresh and activity.current_version_id!=version.id:raise ValueError('RESEARCH_REFRESH_REQUIRES_CURRENT_STEP')
        source=session.get(MembershipTier,UUID(step['from_tier_id'])) if step.get('from_tier_id') else None
        query={} if step.get('research_only') else state.get('query') or {}
        context={k:v for k in ('source_acquisition','residency','prior_participation') if (v:=query.get(k)) is not None}
        context['source_acquisition']=step.get('source_acquisition','UNKNOWN')
        targets.append(ResearchTarget(step_ref=ref,option_version_ref=str(option.id),activity_version_ref=str(version.id),
            edition_ref=activity.edition_key,from_program_ref=str(source.program_id) if source else None,
            from_tier_ref=str(source.id) if source else None,to_program_ref=str(mapping.target_program_id),
            to_tier_ref=str(mapping.target_tier_id),method=option.method,context=context))
    return targets


def research_identity_index(session):
    from sqlalchemy import select
    from journeyplus.knowledge.models import MembershipProgram,MembershipAlias
    from journeyplus.knowledge.publication import canonical_key,display_tier_name
    programs={p.id:p for p in session.scalars(select(MembershipProgram))}
    tiers={t.id:t for t in session.scalars(select(MembershipTier))}
    candidates={}
    def add(name,program,tier=None):
        candidates.setdefault(canonical_key(name),set()).add((str(program),str(tier) if tier else None))
    for p in programs.values():add(p.display_name,p.id)
    for t in tiers.values():
        p=programs[t.program_id]
        add(p.display_name+' '+display_tier_name(p,t),p.id,t.id)
        if len(t.display_name.split())>1:add(t.display_name,p.id,t.id)
    for alias in session.scalars(select(MembershipAlias)):
        if alias.tier_id is None or alias.tier_id in tiers and tiers[alias.tier_id].program_id==alias.program_id:
            add(alias.normalized_alias,alias.program_id,alias.tier_id)
    return {name:{'program_ref':next(iter(values))[0],'tier_ref':next(iter(values))[1]}
            for name,values in candidates.items() if len(values)==1}


def disclose_activity_research_steps(session,state,material,*,limit=12,question=""):
    """Expose bounded investigation subjects, without generating a route or eligibility claim."""
    from journeyplus.knowledge.models import MembershipProgram
    from journeyplus.knowledge.publication import signature,display_tier_name,canonical_key
    activities={a['version_ref']:a['ref'] for a in material.get('data',{}).get('activities',[]) if a.get('version_ref')}
    disclosed=[];seen=set();count=0
    for fact in material.get('data',{}).get('facts',[]):
        if fact.get('field')!='mappings':continue
        option=session.get(ApplicationOptionVersion,UUID(fact['subject_ref']))
        if option is None or str(option.knowledge_version_id) not in activities:continue
        for value in fact['value']:
            mapping=session.get(OptionMapping,UUID(value['ref']))
            if mapping is None or mapping.option_version_id!=option.id:raise ValueError('RESEARCH_MAPPING_VERSION_MISMATCH')
            if mapping.id in seen:continue
            seen.add(mapping.id);count+=1
            if len(disclosed)>=limit:continue
            scope=mapping.source_scope
            tier_ids=scope.get('tier_ids',[]) if scope.get('kind')=='EXACT_TIERS' else []
            source=session.get(MembershipTier,UUID(tier_ids[0])) if len(tier_ids)==1 else None
            if source is None and tier_ids and question:
                explicit=[]
                for tier_id in tier_ids:
                    tier=session.get(MembershipTier,UUID(tier_id));owner=session.get(MembershipProgram,tier.program_id)
                    phrase=canonical_key(owner.display_name+' '+display_tier_name(owner,tier))
                    if re.search(r'(?<![a-z0-9])'+re.escape(phrase)+r'(?![a-z0-9])',canonical_key(question)):explicit.append(tier)
                if len(explicit)==1:source=explicit[0]
            program=session.get(MembershipProgram,source.program_id) if source else None
            ref=signature({'domain':'ACTIVITY_RESEARCH_STEP','option':str(option.id),'mapping':str(mapping.id),'source':str(source.id) if source else None})[:16]
            step={'ref':ref,'option_ref':str(option.id),'mapping_ref':str(mapping.id),'version_ref':str(option.knowledge_version_id),
                  'activity_ref':activities[str(option.knowledge_version_id)],'from_tier_id':str(source.id) if source else None,
                  'from':program.display_name+' '+display_tier_name(program,source) if source else '来源会籍未限定',
                  'to':value['to_program']+' '+value['to_tier'],'source_acquisition':'UNKNOWN','research_only':True}
            state.setdefault('direct_research_steps',{})[ref]=step
            disclosed.append({'ref':ref,'from':step['from'],'to':step['to'],'option_label':option.label,
                              'version_ref':step['version_ref'],'eligibility_not_evaluated':True})
    material.setdefault('data',{})['research_steps']=disclosed
    material.setdefault('coverage',{})['research_subjects']={'observed_count':count,'returned_count':len(disclosed),'has_more':count>len(disclosed)}
    return disclosed
