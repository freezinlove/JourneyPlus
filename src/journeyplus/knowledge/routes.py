from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import date
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
    MembershipProgram, MembershipTier, OptionMapping, OptionPrice, OptionPriceMapping)
from journeyplus.knowledge.publication import display_tier_name, signature
from journeyplus.knowledge.reads import envelope


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
    require_proven_eligibility: bool = False
    # Hypothetical starting tiers are query-local, never implicitly saved as holdings.
    starting_tier_ids: list[UUID] = Field(default_factory=list,max_length=20)


def conditions_result(groups:list[dict],context:dict)->tuple[str,list[dict]]:
    conditions={}
    for g in groups:
        for c in ConditionSet.model_validate(g).items:
            for old in c.supersedes_ids:conditions.pop(old,None)
            conditions[c.condition_id]=c
    checks=[]
    for c in conditions.values():
        actual=context.get(c.topic)
        result="UNKNOWN"
        if c.effect=="INFORMATIONAL":continue
        if c.known_state=="KNOWN" and c.operator!="TEXT" and actual is not None:
            expected=c.value
            if c.topic=="SOURCE_ACQUISITION" and expected=="EARNED_ONLY":expected="EARNED"
            match=(actual==expected if c.operator=="EQ" else actual in expected if c.operator=="IN" else
                   actual>=expected if type(actual) is int and type(expected) is int else None)
            if match is not None:
                if c.effect=="EXCLUDE":match=not match
                result="PASS" if match else "FAIL"
        checks.append({"condition_ref":c.condition_id,"result":result,"reason":c.raw_text,"evidence_refs":list(map(str,c.evidence_ids))})
    result="FAIL" if any(c["result"]=="FAIL" for c in checks) else "UNKNOWN" if any(c["result"]=="UNKNOWN" for c in checks) else "PASS"
    return result,checks


class RouteService:
    def __init__(self,session:Session):self.session=session

    def query(self,query:RouteQuery, *, max_states:int=10000,max_edges:int=20000,deadline_seconds:float=2,
              shortlist:int=8,snapshot:dict[str,str]|None=None)->dict:
        if query.max_amount is not None and not query.currency:raise ValueError("预算上限需要币种")
        if query.free_only and query.max_amount is not None:raise ValueError("免费与金额上限不能同时指定")
        start_time=monotonic();today=date.today()
        versions=snapshot if snapshot is not None else {str(a):str(v) for a,v in self.session.execute(select(Activity.id,Activity.current_version_id).where(Activity.current_version_id.is_not(None),Activity.kind=="STATUS_MATCH",Activity.merged_into_id.is_(None)))}
        version_rows={v.id:v for v in self.session.scalars(select(ActivityKnowledgeVersion).where(ActivityKnowledgeVersion.id.in_([UUID(v) for v in versions.values()]))) }
        for v in version_rows.values():
            a=self.session.get(Activity,v.activity_id)
            if versions.get(str(v.activity_id))!=str(v.id) or v.status!="PUBLISHED" or a.kind!="STATUS_MATCH":raise ValueError("路径快照含非匹配活动或无效版本")
        programs={p.id:p for p in self.session.scalars(select(MembershipProgram))};tiers={t.id:t for t in self.session.scalars(select(MembershipTier))}
        options={o.id:o for o in self.session.scalars(select(ApplicationOptionVersion).where(ApplicationOptionVersion.knowledge_version_id.in_(version_rows)))}
        mappings=list(self.session.scalars(select(OptionMapping).where(OptionMapping.knowledge_version_id.in_(version_rows)).order_by(OptionMapping.id)))
        prices=defaultdict(list)
        for p in self.session.scalars(select(OptionPrice).where(OptionPrice.knowledge_version_id.in_(version_rows))):prices[p.option_version_id].append(p)
        price_mappings=defaultdict(set)
        for row in self.session.scalars(select(OptionPriceMapping).where(OptionPriceMapping.option_version_id.in_(options))):price_mappings[row.price_id].add(row.mapping_id)
        holdings=list(self.session.scalars(select(StatusHolding)))
        roots={h.tier_id for h in holdings if h.tier_id in tiers and (h.valid_until is None or h.valid_until>=today)}|set(query.starting_tier_ids)
        roots &= tiers.keys()
        work=deque((root,[],frozenset({root}),query.source_acquisition) for root in sorted(roots,key=str))
        work.append((None,[],frozenset(),"UNKNOWN"))
        routes=[];steps={};state_count=edge_count=0;stopped=None;reasons=Counter();seen=set()
        while work:
            if state_count>=max_states or edge_count>=max_edges or monotonic()-start_time>=deadline_seconds:
                stopped="STATE_BUDGET" if state_count>=max_states else "EDGE_BUDGET" if edge_count>=max_edges else "TIME_BUDGET";break
            node,path,visited,acquisition=work.popleft();state_count+=1
            for m in mappings:
                if edge_count>=max_edges or monotonic()-start_time>=deadline_seconds:
                    stopped="EDGE_BUDGET" if edge_count>=max_edges else "TIME_BUDGET";break
                edge_count+=1
                o=options[m.option_version_id];v=version_rows[o.knowledge_version_id]
                if m.availability=="UNAVAILABLE" or o.availability=="UNAVAILABLE" or v.facts.get("lifecycle",{}).get("value")=="CLOSED":continue
                ended=False;time_unknown=False
                for window in [v.facts.get("application_window",{}),o.application_window]:
                    end=window.get("end",{})
                    if end.get("known_state")=="KNOWN":
                        value=end["value"]
                        if value.get("precision")=="DATE" and date.fromisoformat(value["date"])<today:ended=True
                        elif value.get("precision")=="INSTANT":
                            from datetime import datetime, UTC
                            if datetime.fromisoformat(value["instant"])<datetime.now(UTC):ended=True
                        elif value.get("precision") in {"MONTH","RELATIVE","UNKNOWN"}:time_unknown=True
                if ended:reasons["申请期限已过"]+=1;continue
                scope=m.source_scope;source_ok=False
                if scope["kind"]=="PUBLIC":source_ok=node is None
                elif node is not None and scope["kind"]=="EXACT_TIERS":source_ok=str(node) in scope["tier_ids"]
                elif node is not None and scope["kind"]=="PROGRAM_ANY_TIER":source_ok=str(tiers[node].program_id)==scope["program_id"]
                if not source_ok or m.target_tier_id in visited:continue
                context={"SOURCE_ACQUISITION":acquisition if acquisition!="UNKNOWN" else None,"RESIDENCY":query.residency}
                condition_groups=[v.facts.get("conditions",{}),o.conditions,m.conditions]
                eligibility,checks=conditions_result(condition_groups,context)
                if not any(g.get("items") for g in condition_groups):
                    eligibility="UNKNOWN"
                    checks.append({"result":"UNKNOWN","reason":"尚无完整资格条件记录，不代表全部申请资格已被证实"})
                if eligibility=="FAIL":reasons["来源或资格不适用"]+=1;continue
                fees=[];conditional=[];alternatives=[];fee_unknown=False;charges={}
                for p in prices[o.id]:
                    if p.target_scope=="EXACT" and p.target_tier_id!=m.target_tier_id:continue
                    if p.mapping_scope=="EXPLICIT" and m.id not in price_mappings[p.id]:continue
                    applies,pc=conditions_result([p.conditions],context)
                    if applies=="FAIL" or p.availability=="UNAVAILABLE":continue
                    value={"ref":str(p.id),"amount":str(p.amount) if p.amount is not None else None,"currency":p.currency,"role":p.fee_role,"conditions":pc,"charge_key":p.charge_key}
                    if applies=="UNKNOWN" or p.combination=="CONDITIONAL":conditional.append(value);fee_unknown=True;continue
                    if p.combination=="ALTERNATIVE":alternatives.append(value);fee_unknown=True;continue
                    if p.known_state!="KNOWN" or p.availability!="AVAILABLE" or p.amount is None:fee_unknown=True;continue
                    group=(p.charge_key,p.fee_role)
                    if group in charges and charges[group]!=(p.amount,p.currency):
                        fee_unknown=True
                        fees=[f for f in fees if (f["charge_key"],f["role"])!=group]
                        charges[group]=None
                        continue
                    if group not in charges:fees.append(value);charges[group]=(p.amount,p.currency)
                if not any(p["role"]=="APPLICATION" for p in fees):fee_unknown=True
                challenge=o.challenge.get("value",{}).get("kind") if o.challenge.get("known_state")=="KNOWN" else "UNKNOWN"
                if not challenge:challenge="UNKNOWN"
                if challenge=="REQUIRED" and not any(p["role"]=="CHALLENGE_SPEND" for p in fees):fee_unknown=True
                sid=signature([str(o.id),str(m.id),str(node),context])[:16]
                steps[sid]={"ref":sid,"option_ref":str(o.id),"mapping_ref":str(m.id),"activity_ref":str(v.activity_id),"version_ref":str(v.id),
                    "from_tier_id":str(node) if node else None,"to_tier_id":str(m.target_tier_id),
                    "from":f"{programs[tiers[node].program_id].display_name} {display_tier_name(programs[tiers[node].program_id],tiers[node])}" if node else None,
                    "to":f"{programs[m.target_program_id].display_name} {display_tier_name(programs[m.target_program_id],tiers[m.target_tier_id])}",
                    "fees":fees,"conditional_items":conditional,"alternative_items":alternatives,"fee_unknown":fee_unknown,
                    "challenge":challenge,"eligibility":eligibility,"constraint_checks":checks,
                    "material_caveats":[x["reason"] for x in checks if x["result"]!="PASS"]+(["期限精度不足，需核对"] if time_unknown else []),"fact_refs":m.evidence_ids,
                    "availability":m.availability if o.availability=="AVAILABLE" else o.availability}
                new_path=path+[sid];key=tuple(new_path)
                if key in seen:continue
                seen.add(key)
                target=programs[m.target_program_id]
                wanted=(query.target_program_id is None or m.target_program_id==query.target_program_id) and (query.target_tier_id is None or m.target_tier_id==query.target_tier_id) and (query.category is None or target.category==query.category) and (query.alliance is None or target.alliance==query.alliance)
                route=self._summarize(new_path,steps,query)
                if wanted:
                    if route["classification"]=="EXCLUDED":reasons["多个硬条件不满足"]+=1
                    else:routes.append(route)
                # All future steps are acquisitions, not earned original holdings.
                # A hard budget/challenge failure cannot be repaired by adding steps.
                if route["classification"]!="EXCLUDED":work.append((m.target_tier_id,new_path,visited|{m.target_tier_id},"MATCHED" if o.method=="MATCH" else "UNKNOWN"))
            if stopped:break
        # Round-robin targets preserves diversity. Full routes stay server-side.
        groups=defaultdict(list)
        for r in sorted(routes,key=lambda r:(r["classification"]!="MATCH",r["step_count"],r["ref"])):groups[r["to"]].append(r)
        cards=[]
        while len(cards)<min(shortlist,12) and any(groups.values()):
            for name in sorted(groups):
                if groups[name] and len(cards)<min(shortlist,12):cards.append(groups[name].pop(0))
        out=envelope({"query":query.model_dump(mode="json"),"cards":cards,"steps":{r:steps[r] for c in cards for r in c["step_refs"]},"reason_counts":dict(reasons)},
                     snapshot=versions,count=len(routes),returned=len(cards),partial=stopped is not None,reason=stopped)
        out["coverage"].update(presentation_has_more=len(routes)>len(cards),expanded_states=state_count,checked_edges=edge_count)
        out["server_routes"]={r["ref"]:r for r in routes};out["server_steps"]=steps;out["snapshot"]=versions
        out["expansions"]=[{"ref":r["ref"],"kind":"ROUTE","aspects":["ELIGIBILITY","PRICE"],"reason":"展开完整方案"} for r in cards]
        return out

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
        classification="EXCLUDED" if len(violations)>1 or (violations and unknowns) else "NEARBY" if violations else "UNKNOWN" if unknowns else "MATCH"
        return {"ref":signature(path)[:16],"from":items[0]["from"],"to":items[-1]["to"],"step_refs":path,"step_count":len(path),
                "classification":classification,"violations":violations,"unknowns":unknowns,
                "cost":{"state":"PARTIAL" if unknown and totals else "UNKNOWN" if unknown else "KNOWN",
                        "totals":[{"currency":c,"role":r,"amount":str(a)} for (c,r),a in totals.items()],
                        "conditional_items":[p for x in items for p in x["conditional_items"]],"alternative_items":[p for x in items for p in x["alternative_items"]],
                        "is_proven_free":bool(app) and not unknown and all(a==0 for a in app.values()),"scope":"申请费用；挑战支出单列"},
                "eligibility":"UNKNOWN" if any(x["eligibility"]=="UNKNOWN" for x in items) else "PASS",
                "challenge":challenge,"material_caveats":[c for x in items for c in x["material_caveats"]],"needs_inspection":False,
                "fact_refs":list(dict.fromkeys(f for x in items for f in x["fact_refs"]))}
