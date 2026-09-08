from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import UTC,datetime,date
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic
from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.contracts import StrictModel
from journeyplus.models import StatusHolding
from journeyplus.knowledge.contracts import ConditionSet
from journeyplus.knowledge.models import (Activity, ActivityKnowledgeVersion, ApplicationOptionVersion,
    ActivityObservationState, MembershipProgram, MembershipTier, OptionMapping, OptionPrice, OptionPriceMapping)
from journeyplus.knowledge.publication import display_tier_name, signature, _evidence_ids
from journeyplus.knowledge.reads import envelope
from journeyplus.knowledge.temporal import window_state


class RouteQuery(StrictModel):
    target_program_id: UUID | None = None
    target_tier_id: UUID | None = None
    alliance: str | None = None
    category: str | None = None
    free_only: bool = False
    max_amount: Decimal | None = Field(default=None,ge=0)
    currency: str | None = Field(default=None,pattern=r"^[A-Z]{3}$")
    allow_challenge: bool | None = None
    source_acquisition: Literal["EARNED","MATCHED","UNKNOWN"] = "UNKNOWN"
    residency: str | None = None
    prior_participation: str | None = None
    preferences: list[Literal['FEWER_STEPS','LOWER_KNOWN_FEE','LESS_UNCERTAINTY']] = Field(default_factory=list,max_length=3)
    require_proven_eligibility: bool = False
    # Hypothetical starting tiers are query-local, never implicitly saved as holdings.
    starting_tier_ids: list[UUID] = Field(default_factory=list,max_length=20)
    use_saved_holdings: bool | None = None


def conditions_result(groups:list[dict],context:dict)->tuple[str,list[dict]]:
    conditions=[]
    for g in groups:
        for c in ConditionSet.model_validate(g).items:
            conditions=[old for old in conditions if old.condition_id not in c.supersedes_ids]
            if c not in conditions:conditions.append(c)
    checks=[]
    for c in conditions:
        actual=context.get(c.topic)
        result="UNKNOWN"
        if c.effect=="INFORMATIONAL":continue
        if c.known_state=="KNOWN" and c.operator!="TEXT" and actual is not None:
            expected=c.value
            if c.topic=="SOURCE_ACQUISITION" and expected=="EARNED_ONLY":expected="EARNED"
            match=(actual==expected if c.operator=="EQ" else actual in expected if c.operator=="IN" else
                   actual>=expected if type(actual) is int and type(expected) is int else None)
            if c.topic=='RESIDENCY' and c.operator in {'EQ','IN'}:
                from journeyplus.knowledge.countries import country_equal,country_in
                match=country_equal(actual,expected) if c.operator=='EQ' else country_in(actual,expected)
            if match is not None:
                if c.effect=="EXCLUDE":match=not match
                result="PASS" if match else "FAIL"
        checks.append({"condition_ref":c.condition_id,"topic":c.topic,"operator":c.operator,"effect":c.effect,"result":result,"actual":actual,"expected":c.value,
                       "reason":c.raw_text,"evidence_refs":list(map(str,c.evidence_ids))})
    result="FAIL" if any(c["result"]=="FAIL" for c in checks) else "UNKNOWN" if any(c["result"]=="UNKNOWN" for c in checks) else "PASS"
    return result,checks


@dataclass(frozen=True)
class HoldingSnapshot:
    id: UUID
    tier_id: UUID | None
    revision: int
    valid_until: date | None


class RouteService:
    def __init__(self,session:Session,*,holding_snapshot=None):
        self.session=session
        self.holding_snapshot=holding_snapshot

    def holdings(self):
        if self.holding_snapshot is not None:return self.holding_snapshot
        return list(self.session.scalars(select(StatusHolding).order_by(StatusHolding.id)))

    def current_snapshot(self):
        return {str(a):str(v) for a,v in self.session.execute(select(Activity.id,Activity.current_version_id).where(
            Activity.current_version_id.is_not(None),Activity.kind=='STATUS_MATCH',Activity.merged_into_id.is_(None)))}

    def evaluation_context(self, now=None):
        """Mutable inputs that can change route eligibility without a publication."""
        now=now or datetime.now(UTC)
        holdings=[{'id':str(h.id),'tier':str(h.tier_id),'revision':h.revision,
                   'until':h.valid_until.isoformat() if h.valid_until else None}
                  for h in self.holdings()]
        observations=[{'activity':str(o.activity_id),'freshness':o.freshness,
                       'checked':o.last_checked_at.isoformat() if o.last_checked_at else None}
                      for o in self.session.scalars(select(ActivityObservationState).order_by(ActivityObservationState.activity_id))]
        pending=[str(a) for a in self.session.scalars(select(Activity.id).where(Activity.kind=='STATUS_MATCH',
                 Activity.current_version_id.is_(None),Activity.merged_into_id.is_(None)).order_by(Activity.id))]
        windows=[(str(o.id),window_state(o.application_window,now)) for o in self.session.scalars(select(ApplicationOptionVersion).join(ActivityKnowledgeVersion,ApplicationOptionVersion.knowledge_version_id==ActivityKnowledgeVersion.id).join(Activity,Activity.current_version_id==ActivityKnowledgeVersion.id))]
        windows += [(str(v.id),window_state(v.facts.get('application_window',{}),now)) for v in self.session.scalars(select(ActivityKnowledgeVersion).join(Activity,Activity.current_version_id==ActivityKnowledgeVersion.id))]
        catalog=[(str(p.id),p.category,p.alliance) for p in self.session.scalars(select(MembershipProgram).order_by(MembershipProgram.id))]
        from journeyplus.knowledge.models import MembershipAlias
        from journeyplus.knowledge.catalog_identity import REVIEWED_PROGRAM_SPELLINGS
        identity_aliases=[(str(a.program_id),str(a.tier_id),a.normalized_alias) for a in self.session.scalars(select(MembershipAlias).where(MembershipAlias.origin=='OFFICIAL_TABLE_TARGET_LABEL').order_by(MembershipAlias.id))]
        return signature({'catalog':catalog,'identity_aliases':identity_aliases,'reviewed_spellings':REVIEWED_PROGRAM_SPELLINGS,'date':now.date().isoformat(),'windows':sorted(windows),'holdings':holdings,'observations':observations,'pending':pending})

    def query(self,query:RouteQuery, *, max_states:int=10000,max_edges:int=20000,deadline_seconds:float=2,
              shortlist:int=8,snapshot:dict[str,str]|None=None)->dict:
        if query.max_amount is not None and not query.currency:raise ValueError("预算上限需要币种")
        if query.free_only and query.max_amount is not None:raise ValueError("免费与金额上限不能同时指定")
        start_time=monotonic();now=datetime.now(UTC);today=now.date();evaluation_context=self.evaluation_context(now)
        versions=snapshot if snapshot is not None else self.current_snapshot()
        version_rows={v.id:v for v in self.session.scalars(select(ActivityKnowledgeVersion).where(ActivityKnowledgeVersion.id.in_([UUID(v) for v in versions.values()]))) }
        observations={o.activity_id:o for o in self.session.scalars(select(ActivityObservationState))}
        pending_activity_ids=list(self.session.scalars(select(Activity.id).where(Activity.kind=='STATUS_MATCH',Activity.current_version_id.is_(None),Activity.merged_into_id.is_(None)))) if snapshot is None else []
        for v in version_rows.values():
            a=self.session.get(Activity,v.activity_id)
            if versions.get(str(v.activity_id))!=str(v.id) or v.status!="PUBLISHED" or a.kind!="STATUS_MATCH":raise ValueError("路径快照含非匹配活动或无效版本")
        programs={p.id:p for p in self.session.scalars(select(MembershipProgram))};tiers={t.id:t for t in self.session.scalars(select(MembershipTier))}
        from journeyplus.knowledge.catalog_identity import route_identities,program_key
        identities,metadata=route_identities(self.session,programs,tiers)
        options={o.id:o for o in self.session.scalars(select(ApplicationOptionVersion).where(ApplicationOptionVersion.knowledge_version_id.in_(version_rows)))}
        mappings=list(self.session.scalars(select(OptionMapping).where(OptionMapping.knowledge_version_id.in_(version_rows)).order_by(OptionMapping.id)))
        exact_edges=defaultdict(list);program_edges=defaultdict(list);category_edges=defaultdict(list);public_edges=[]
        for mapping in mappings:
            scope=mapping.source_scope
            if scope['kind']=='EXACT_TIERS':
                for node in {identities[UUID(tier)] for tier in scope['tier_ids']}:
                    exact_edges[node].append(mapping)
            elif scope['kind']=='PROGRAM_ANY_TIER':program_edges[program_key(programs[UUID(scope['program_id'])])].append(mapping)
            elif scope['kind']=='CATEGORY_RULE':category_edges[scope['category']].append(mapping)
            elif scope['kind']=='PUBLIC':public_edges.append(mapping)
        prices=defaultdict(list)
        for p in self.session.scalars(select(OptionPrice).where(OptionPrice.knowledge_version_id.in_(version_rows))):prices[p.option_version_id].append(p)
        price_mappings=defaultdict(set)
        for row in self.session.scalars(select(OptionPriceMapping).where(OptionPriceMapping.option_version_id.in_(options))):price_mappings[row.price_id].add(row.mapping_id)
        holdings=self.holdings()
        remaining_days={}
        for h in holdings:
            if h.tier_id in identities and h.valid_until is not None and h.valid_until>=today:
                node=identities[h.tier_id]
                remaining_days[node]=max(remaining_days.get(node,0),(h.valid_until-today).days)
        use_saved=query.use_saved_holdings if query.use_saved_holdings is not None else not bool(query.starting_tier_ids)
        roots=({h.tier_id for h in holdings if h.tier_id in tiers and (h.valid_until is None or h.valid_until>=today)} if use_saved else set())|set(query.starting_tier_ids)
        unresolved_holdings=sum(h.tier_id not in tiers for h in holdings if use_saved and (h.valid_until is None or h.valid_until>=today))
        unknown_alliances=len({m.target_program_id for m in mappings if query.alliance and metadata[m.target_program_id]['alliance'] is None})
        roots &= tiers.keys()
        roots={identities[root] for root in roots}
        work=deque((root,[],frozenset({root}),query.source_acquisition) for root in sorted(roots,key=str))
        work.append((None,[],frozenset(),"UNKNOWN"))
        routes=[];steps={};state_count=edge_count=0;stopped=None;reasons=Counter();seen=set()
        while work:
            if state_count>=max_states or edge_count>=max_edges or monotonic()-start_time>=deadline_seconds:
                stopped="STATE_BUDGET" if state_count>=max_states else "EDGE_BUDGET" if edge_count>=max_edges else "TIME_BUDGET";break
            node,path,visited,acquisition=work.popleft();state_count+=1
            if node is None:candidates=public_edges
            else:
                source_program=programs[tiers[node].program_id]
                candidates=sorted([*exact_edges[node],*program_edges[program_key(source_program)],
                    *category_edges[metadata[source_program.id]['category']]],key=lambda m:str(m.id))
            for m in candidates:
                if edge_count>=max_edges or monotonic()-start_time>=deadline_seconds:
                    stopped="EDGE_BUDGET" if edge_count>=max_edges else "TIME_BUDGET";break
                edge_count+=1
                o=options[m.option_version_id];v=version_rows[o.knowledge_version_id]
                target_node=identities[m.target_tier_id]
                if m.availability=="UNAVAILABLE" or o.availability=="UNAVAILABLE" or v.facts.get("lifecycle",{}).get("value")=="CLOSED":continue
                time_states=[window_state(w,now) for w in [v.facts.get('application_window',{}),o.application_window]]
                ended='ENDED' in time_states;not_started='NOT_STARTED' in time_states;time_unknown='UNKNOWN' in time_states
                if ended:reasons["申请期限已过"]+=1;continue
                if not_started:reasons["尚未开放申请"]+=1;continue
                scope=m.source_scope;source_ok=False
                if scope["kind"]=="PUBLIC":source_ok=node is None
                elif node is not None and scope["kind"]=="EXACT_TIERS":source_ok=node in {identities.get(UUID(tier)) for tier in scope['tier_ids']}
                elif node is not None and scope["kind"]=="PROGRAM_ANY_TIER":source_ok=program_key(programs[tiers[node].program_id])==program_key(programs[UUID(scope['program_id'])])
                elif node is not None and scope["kind"]=="CATEGORY_RULE":source_ok=scope['category']!='OTHER' and metadata[tiers[node].program_id]['category']==scope['category']
                if not source_ok or target_node in visited:continue
                context={"SOURCE_ACQUISITION":acquisition if acquisition!="UNKNOWN" else None,"RESIDENCY":query.residency,
                         "PRIOR_PARTICIPATION":query.prior_participation,
                         "MIN_REMAINING_VALIDITY":remaining_days.get(node) if not path else None}
                condition_groups=[v.facts.get("conditions",{}),o.conditions,m.conditions]
                eligibility,checks=conditions_result(condition_groups,context)
                if time_unknown:
                    checks.append({'result':'UNKNOWN','reason':'申请期限或时区尚未核实','topic':'APPLICATION_WINDOW'})
                    if eligibility!='FAIL':eligibility='UNKNOWN'
                if scope['kind']=='CATEGORY_RULE':
                    checks.append({'result':'UNKNOWN','reason':scope['rule_text'],'evidence_refs':scope['evidence_ids']})
                    if eligibility!='FAIL':eligibility='UNKNOWN'
                if not any(g.get("items") for g in condition_groups):
                    eligibility="UNKNOWN"
                    checks.append({"result":"UNKNOWN","reason":"尚无完整资格条件记录，不代表全部申请资格已被证实"})
                if eligibility=="FAIL":reasons["来源或资格不适用"]+=1;continue
                fees=[];conditional=[];alternatives=[];fee_unknown=False;fee_conflict=False;charges={};price_evidence=set()
                for p in prices[o.id]:
                    if p.target_scope=="EXACT" and p.target_tier_id!=m.target_tier_id:continue
                    if p.mapping_scope=="EXPLICIT" and m.id not in price_mappings[p.id]:continue
                    price_evidence.update(p.evidence_ids)
                    price_evidence.update(map(str,_evidence_ids(p.conditions)))
                    applies,pc=conditions_result([p.conditions],context)
                    if applies=="FAIL" or p.availability=="UNAVAILABLE":continue
                    value={"ref":str(p.id),"amount":str(p.amount) if p.amount is not None else None,"currency":p.currency,"role":p.fee_role,"conditions":pc,"charge_key":p.charge_key,
                           "known_state":p.known_state,"availability":p.availability,"alternative_group":p.alternative_group}
                    if p.known_state=='CONFLICT' or p.availability=='CONFLICT':
                        conditional.append({**value,'applicability':'CONFLICT','reason':'费用来源存在尚未解决的冲突'})
                        fee_unknown=True;fee_conflict=True;continue
                    if applies=="UNKNOWN" or p.combination=="CONDITIONAL":conditional.append(value);fee_unknown=True;continue
                    if p.combination=="ALTERNATIVE":alternatives.append(value);fee_unknown=True;continue
                    if p.known_state!="KNOWN" or p.availability!="AVAILABLE" or p.amount is None:
                        conditional.append({**value,'applicability':'UNKNOWN','reason':'费用数值或当前适用性尚未证实'})
                        fee_unknown=True;continue
                    group=(p.charge_key,p.fee_role)
                    if group in charges and charges[group]!=(p.amount,p.currency):
                        fee_unknown=True;fee_conflict=True
                        competing=[f for f in fees if (f['charge_key'],f['role'])==group]
                        conditional.extend({**f,'applicability':'CONFLICT','reason':'同一收费项目存在互相矛盾的金额或币种，不能累加或任选'} for f in [*competing,value])
                        fees=[f for f in fees if (f["charge_key"],f["role"])!=group]
                        charges[group]=None
                        continue
                    if group not in charges:fees.append(value);charges[group]=(p.amount,p.currency)
                if not any(p["role"]=="APPLICATION" for p in fees):fee_unknown=True
                challenge=o.challenge.get("value",{}).get("kind") if o.challenge.get("known_state")=="KNOWN" else "UNKNOWN"
                if not challenge:challenge="UNKNOWN"
                if challenge=="REQUIRED" and not any(p["role"]=="CHALLENGE_SPEND" for p in fees):fee_unknown=True
                sid=signature([str(o.id),str(m.id),str(node),context,evaluation_context])[:16]
                observation=observations.get(v.activity_id)
                freshness=observation.freshness if observation else 'UNKNOWN'
                fact_refs=set(m.evidence_ids)|price_evidence
                for value in (v.facts,o.conditions,m.conditions,o.source_scope,m.source_scope,o.challenge,o.application_window,o.status_validity,o.action_link):
                    fact_refs.update(map(str,_evidence_ids(value)))
                steps[sid]={"ref":sid,"option_ref":str(o.id),"mapping_ref":str(m.id),"activity_ref":str(v.activity_id),"version_ref":str(v.id),
                    "from_tier_id":str(node) if node else None,"to_tier_id":str(target_node),
                    "target_category":metadata[m.target_program_id]['category'],"target_alliance":metadata[m.target_program_id]['alliance'],
                    "from":f"{programs[tiers[node].program_id].display_name} {display_tier_name(programs[tiers[node].program_id],tiers[node])}" if node else None,
                    "to":f"{programs[m.target_program_id].display_name} {display_tier_name(programs[m.target_program_id],tiers[m.target_tier_id])}",
                    "fees":fees,"conditional_items":conditional,"alternative_items":alternatives,"fee_unknown":fee_unknown,"fee_conflict":fee_conflict,
                    "challenge":challenge,"eligibility":eligibility,"constraint_checks":checks,"source_acquisition":acquisition,
                    "material_caveats":[x["reason"] for x in checks if x["result"]!="PASS"]+(["期限精度不足，需核对"] if time_unknown else [])+(['活动资料陈旧或本次检查不完整，需核对当前规则'] if freshness in {'STALE','INCOMPLETE'} else []),"fact_refs":sorted(fact_refs),
                    "application_window":{"activity":v.facts.get("application_window",{}),"option":o.application_window},"status_validity":o.status_validity,
                    "freshness":freshness,
                    "availability":'UNKNOWN' if freshness in {'STALE','INCOMPLETE'} else m.availability if o.availability=="AVAILABLE" else o.availability}
                new_path=path+[sid];key=tuple(new_path)
                if key in seen:continue
                seen.add(key)
                target=programs[m.target_program_id]
                wanted=(query.target_program_id is None or query.target_program_id in programs and program_key(target)==program_key(programs[query.target_program_id])) and (query.target_tier_id is None or target_node==identities.get(query.target_tier_id)) and (query.category is None or metadata[target.id]['category']==query.category) and (query.alliance is None or metadata[target.id]['alliance']==query.alliance)
                route=self._summarize(new_path,steps,query)
                if wanted:
                    if route["classification"]=="EXCLUDED":reasons["硬条件失败且不满足单项可调整方案要求"]+=1
                    else:routes.append(route)
                # All future steps are acquisitions, not earned original holdings.
                # A hard budget/challenge failure cannot be repaired by adding steps.
                if route["classification"]!="EXCLUDED":work.append((target_node,new_path,visited|{target_node},"MATCHED" if o.method=="MATCH" else "UNKNOWN"))
            if stopped:break
        # Round-robin targets preserves diversity. Full routes stay server-side.
        from journeyplus.knowledge.selection import order_candidates
        ordered,group_overview=order_candidates(routes,query.preferences)
        cards=ordered[:min(shortlist,12)]
        out=envelope({"query":query.model_dump(mode="json"),"groups":group_overview,"cards":cards,"steps":{r:steps[r] for c in cards for r in c["step_refs"]},"reason_counts":dict(reasons)},
                     snapshot=versions,count=len(routes),returned=len(cards),partial=stopped is not None,reason=stopped)
        out["coverage"].update(presentation_has_more=len(routes)>len(cards),expanded_states=state_count,checked_edges=edge_count)
        unresolved={version_rows[m.knowledge_version_id].activity_id for m in mappings
                    if m.source_scope.get('kind')=='UNKNOWN' and m.availability!='UNAVAILABLE'
                    and version_rows[m.knowledge_version_id].facts.get('lifecycle',{}).get('value')!='CLOSED'}
        mapped_versions={m.knowledge_version_id for m in mappings}
        unresolved.update(v.activity_id for v in version_rows.values() if v.id not in mapped_versions
                          and v.facts.get('lifecycle',{}).get('value')!='CLOSED')
        unresolved.update(v.activity_id for v in version_rows.values() if any(
            note.get('code')=='MAPPING_TABLE_INCOMPLETE' for note in v.validation_errors)
            and v.facts.get('lifecycle',{}).get('value')!='CLOSED')
        out['coverage'].update(knowledge_complete=not (pending_activity_ids or unresolved),pending_activity_count=len(pending_activity_ids),
                               incomplete_published_activity_count=len(unresolved))
        if pending_activity_ids or unresolved:
            out['status']='PARTIAL'
            out['coverage'].update(search_complete=False,searched_published_graph_complete=stopped is None,stopped_reason=stopped or 'KNOWLEDGE_GAPS')
            out['caveats'].append('仍有匹配活动未发布或来源映射未核实；当前结果不能证明没有其他路径。')
        out['coverage'].update(unresolved_holding_count=unresolved_holdings,unresolved_alliance_program_count=unknown_alliances)
        if unresolved_holdings or unknown_alliances:
            out['status']='PARTIAL';out['coverage']['search_complete']=False
            out['coverage']['stopped_reason']=out['coverage'].get('stopped_reason') or 'CATALOG_METADATA_GAPS'
            if unresolved_holdings:out['caveats'].append(f'有 {unresolved_holdings} 项已保存会籍尚未关联规范等级，未用于路径计算；不能据此判断这些会籍没有机会。')
            if unknown_alliances:out['caveats'].append(f'有 {unknown_alliances} 个目标项目的联盟尚未核实，不能据此判定没有该联盟的机会。')
        out["server_routes"]={r["ref"]:r for r in ordered};out["server_steps"]=steps;out["snapshot"]=versions
        out["expansions"]=[{"ref":r["ref"],"kind":"ROUTE","aspects":["ELIGIBILITY","PRICE"],"reason":"展开完整方案"} for r in cards]
        from journeyplus.knowledge.transport import ServerRouteResult
        return ServerRouteResult.model_validate(out).model_dump(mode='json',exclude_unset=True)

    def _summarize(self,path,steps,q):
        items=[steps[x] for x in path];totals=defaultdict(Decimal);unknown=any(x["fee_unknown"] for x in items)
        for x in items:
            for f in x["fees"]:totals[(f["currency"],f["role"])]+=Decimal(f["amount"])
        violations=[];unknowns=[]
        app=defaultdict(Decimal)
        for (currency,_role),amount in totals.items():app[currency]+=amount
        if q.free_only:
            if any(v>0 for v in app.values()):violations.append("free_only")
            elif unknown:unknowns.append("free_only")
        if q.max_amount is not None:
            if app.get(q.currency,Decimal(0))>q.max_amount:violations.append("max_amount")
            elif unknown or any(cur!=q.currency and amount>0 for cur,amount in app.items()):unknowns.append("max_amount")
        challenge="REQUIRED" if any(x["challenge"]=="REQUIRED" for x in items) else "UNKNOWN" if any(x["challenge"]=="UNKNOWN" for x in items) else "NONE"
        if q.allow_challenge is False:
            if challenge=="REQUIRED":violations.append("allow_challenge")
            elif challenge=="UNKNOWN":unknowns.append("allow_challenge")
        if q.require_proven_eligibility and any(x["eligibility"]=="UNKNOWN" for x in items):unknowns.append("eligibility")
        if any(x["availability"]!="AVAILABLE" for x in items):unknowns.append("availability")
        classification="EXCLUDED" if len(violations)>1 or (violations and (unknowns or unknown)) else "NEARBY" if violations else "UNKNOWN" if unknowns else "MATCH"
        return {"ref":signature({'steps':path,'query':q.model_dump(mode='json')})[:16],"from":items[0]["from"],"to":items[-1]["to"],"step_refs":path,"step_count":len(path),
                "classification":classification,"violations":violations,"unknowns":unknowns,
                "cost":{"state":"CONFLICT" if any(x.get("fee_conflict") for x in items) else "PARTIAL" if unknown and totals else "UNKNOWN" if unknown else "KNOWN",
                        "totals":[{"currency":c,"role":r,"amount":str(a)} for (c,r),a in totals.items()],
                        "conditional_items":[p for x in items for p in x["conditional_items"]],"alternative_items":[p for x in items for p in x["alternative_items"]],
                        "is_proven_free":bool(app) and not unknown and all(a==0 for a in app.values()),"scope":"已确认必付费用按角色和币种分别列出；条件及互斥费用不计入确定合计"},
                "eligibility":"UNKNOWN" if any(x["eligibility"]=="UNKNOWN" for x in items) else "PASS",
                "challenge":challenge,"material_caveats":[c for x in items for c in x["material_caveats"]],
                "needs_inspection":unknown or challenge=='UNKNOWN' or bool(unknowns) or any(x['eligibility']=='UNKNOWN' for x in items),
                "fact_refs":list(dict.fromkeys(f for x in items for f in x["fact_refs"]))}
