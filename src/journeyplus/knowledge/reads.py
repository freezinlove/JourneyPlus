from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from journeyplus.knowledge.models import (Activity, ActivityBrief, ActivityDocument, ActivityKnowledgeVersion,
    ActivityObservationState, ApplicationOptionVersion, DocumentSection, EvidenceReference,
    MembershipProgram, MembershipTier, OptionMapping, OptionPrice)
from journeyplus.knowledge.publication import canonical_key, signature
from journeyplus.knowledge.sources import expand_evidence


def envelope(data, *, snapshot=None, status="OK", count=0, returned=None, partial=False, reason=None):
    return {"schema_version":1,"status":status,"snapshot_ref":signature(snapshot or {})[:20],"data":data,
            "coverage":{"search_complete":not partial,"scope_description":"所选活动的已发布知识",
                        "observed_count":count,"returned_count":count if returned is None else returned,
                        "presentation_has_more":partial,"stopped_reason":reason},
            "caveats":[],"expansions":[],"provenance":[]}


class ActivityReadService:
    def __init__(self,session:Session):self.session=session

    def snapshot(self)->dict[str,str]:
        return {str(a):str(v) for a,v in self.session.execute(select(Activity.id,Activity.current_version_id).where(Activity.current_version_id.is_not(None),Activity.merged_into_id.is_(None)))}

    def locate(self, *, ref:str|None=None, text:str|None=None, limit:int=5)->list[Activity]:
        if ref:
            try: row=self.session.get(Activity,UUID(ref))
            except ValueError: row=None
            if row: return [row]
        query=canonical_key(text or "")
        rows=[]
        for a in self.session.scalars(select(Activity).where(Activity.merged_into_id.is_(None)).order_by(Activity.identity_key)):
            p=self.session.get(MembershipProgram,a.primary_program_id) if a.primary_program_id else None
            v=self.session.get(ActivityKnowledgeVersion,a.current_version_id) if a.current_version_id else None
            if query and any(query in canonical_key(x) for x in [p.display_name if p else "",v.facts.get("title","") if v else "",a.identity_key]):
                rows.append(a)
        return rows[:limit+1]

    def detail(self, activity_id:UUID, version_id:UUID|None=None)->dict:
        a=self.session.get(Activity,activity_id)
        if a is None: raise LookupError("活动不存在")
        v=self.session.get(ActivityKnowledgeVersion,version_id or a.current_version_id) if (version_id or a.current_version_id) else None
        if v is None: return {"ref":str(a.id),"status":"PENDING_KNOWLEDGE","caveats":["资料关联待核对，尚未发布活动知识"]}
        if v.activity_id!=a.id or v.status!="PUBLISHED":raise ValueError("活动版本不匹配")
        observation=self.session.get(ActivityObservationState,a.id)
        options=[]
        for o in self.session.scalars(select(ApplicationOptionVersion).where(ApplicationOptionVersion.knowledge_version_id==v.id).order_by(ApplicationOptionVersion.id)):
            mappings=[]
            for m in self.session.scalars(select(OptionMapping).where(OptionMapping.option_version_id==o.id)):
                tier=self.session.get(MembershipTier,m.target_tier_id);program=self.session.get(MembershipProgram,m.target_program_id)
                mappings.append({"ref":str(m.id),"source_scope":m.source_scope,"to_program":program.display_name,"to_tier":tier.display_name,
                                 "target_program_id":str(m.target_program_id),"target_tier_id":str(m.target_tier_id),
                                 "availability":m.availability,"conditions":m.conditions,"evidence_ids":m.evidence_ids})
            prices=[{"ref":str(p.id),"target_tier_id":str(p.target_tier_id) if p.target_tier_id else None,
                     "target_scope":p.target_scope,"mapping_scope":p.mapping_scope,"amount":str(p.amount) if p.amount is not None else None,
                     "currency":p.currency,"known_state":p.known_state,"fee_role":p.fee_role,"combination":p.combination,
                     "conditions":p.conditions,"raw_text":p.raw_text,"availability":p.availability,"evidence_ids":p.evidence_ids}
                    for p in self.session.scalars(select(OptionPrice).where(OptionPrice.option_version_id==o.id))]
            options.append({"ref":str(o.id),"logical_ref":str(o.option_id),"label":o.label,"method":o.method,
                            "source_scope":o.source_scope,"conditions":o.conditions,"challenge":o.challenge,
                            "application_window":o.application_window,"status_validity":o.status_validity,
                            "action_link":o.action_link,"availability":o.availability,"mappings":mappings,"prices":prices})
        briefs=[{"kind":b.brief_kind,"status":b.status,"content":b.content,"version_ref":str(v.id)} for b in self.session.scalars(select(ActivityBrief).where(ActivityBrief.knowledge_version_id==v.id))]
        return {"ref":str(a.id),"version_ref":str(v.id),"current_version_ref":str(a.current_version_id),"is_current":a.current_version_id==v.id,
                "name":v.facts["title"],"edition":a.edition_key,"kind":a.kind,"facts":v.facts,"published_at":v.published_at.isoformat(),
                "freshness":observation.freshness if observation else "INCOMPLETE","options":options,"briefs":briefs}

    def materials(self, *, selector:dict, question:str, view:str="AUTO", aspects:list[str]|None=None,
                  evidence_refs:list[str]|None=None, section_refs:list[str]|None=None, version_ref:str|None=None, max_chars:int=14000)->dict:
        max_chars=min(max(max_chars,1000),24000)
        rows=self.locate(ref=selector.get("ref"),text=selector.get("text"))
        if len(rows)!=1:
            return envelope({"activities":[{"ref":str(a.id),"edition":a.edition_key,"name":self.session.get(MembershipProgram,a.primary_program_id).display_name if a.primary_program_id else a.identity_key} for a in rows[:5]]},
                            status="AMBIGUOUS" if rows else "NEEDS_INPUT",count=len(rows),returned=min(5,len(rows)),partial=len(rows)>5)
        detail=self.detail(rows[0].id,UUID(version_ref) if version_ref else None)
        if detail.get("status")=="PENDING_KNOWLEDGE":return envelope(detail,status="UNAVAILABLE")
        vid=UUID(detail["version_ref"]);snapshot={detail["ref"]:str(vid)}
        topics=set(aspects or [])
        if not topics:
            from journeyplus.knowledge.sources import TOPICS
            topics={k for k,p in TOPICS.items() if re.search(p,question,re.I)}
        facts=[]
        relevant={"PRICE":"prices","ELIGIBILITY":"conditions","CHALLENGE":"challenge","WINDOW":"application_window",
                  "VALIDITY":"status_validity","APPLICATION":"action_link"}
        for o in detail["options"]:
            for aspect,field in relevant.items():
                if not topics or aspect in topics:
                    facts.append({"ref":f"{vid}/{o['ref']}/{field}","subject_ref":o["ref"],"label":o["label"],"field":field,"value":o[field]})
            # Material conditions are always carried even when the question is about price.
            if topics and "ELIGIBILITY" not in topics and o["conditions"].get("items"):
                facts.append({"ref":f"{vid}/{o['ref']}/conditions","subject_ref":o["ref"],"label":o["label"],"field":"conditions","value":o["conditions"]})
        bindings=list(self.session.scalars(select(ActivityDocument).where(ActivityDocument.knowledge_version_id==vid)))
        allowed={b.document_version_id:{UUID(x) for x in b.section_scope} or None for b in bindings}
        snippets=[];size=0;partial=False;expansions=[]
        if view in {"EVIDENCE","DETAIL"} or topics or evidence_refs or section_refs:
            if evidence_refs:
                for ref in evidence_refs:
                    e=self.session.get(EvidenceReference,UUID(ref))
                    if e is None or e.document_version_id not in allowed:raise ValueError("依据不属于当前活动版本")
                    expanded=expand_evidence(self.session,e.id,allowed_sections=allowed[e.document_version_id])
                    group=[x for x in expanded["sections"] if x["ref"] not in {n["ref"] for n in snippets}]
                    length=sum(len(x["text"]) for x in group)
                    if size+length>max_chars:
                        partial=True;expansions.extend(x["ref"] for x in group)
                    else:snippets.extend(group);size+=length
            else:
                for b in bindings:
                    sections=list(self.session.scalars(select(DocumentSection).where(DocumentSection.document_version_id==b.document_version_id).order_by(DocumentSection.ordinal)))
                    requested={UUID(x) for x in section_refs or []}
                    scope=allowed[b.document_version_id]
                    selected=[x for x in sections if (x.id in requested if requested else (not topics or topics.intersection(x.topics)) and x.kind!="ROW")]
                    by_id={x.id:x for x in sections}
                    for root in selected:
                        ids={root.id,*[UUID(r) for r in root.related_section_ids]}
                        group=[x for x in sections if x.id in ids and (scope is None or x.id in scope) and str(x.id) not in {n["ref"] for n in snippets}]
                        length=sum(len(x.body) for x in group)
                        if size+length>max_chars:
                            partial=True;expansions.append(str(root.id));continue
                        snippets.extend({"ref":str(x.id),"document_version_ref":str(b.document_version_id),"heading":x.heading_path,"text":x.body,"source_role":b.role} for x in group)
                        size+=length
                if section_refs:
                    for ref in section_refs:
                        section=self.session.get(DocumentSection,UUID(ref))
                        if section is None or section.document_version_id not in allowed or (allowed[section.document_version_id] is not None and section.id not in allowed[section.document_version_id]):
                            raise ValueError("章节不属于当前活动版本")
        summary={k:detail[k] for k in ["ref","name","edition","version_ref","published_at","freshness","is_current"]}
        summary["lifecycle"]=detail["facts"].get("lifecycle")
        summary["material_caveats"]=detail["facts"].get("caveats",[])
        out=envelope({"activities":[summary],"facts":facts,"snippets":snippets,"changes":[]},snapshot=snapshot,
                     status="PARTIAL" if partial else "OK",count=len(facts),partial=partial,reason="CONTENT_BUDGET" if partial else None)
        out["expansions"]=[{"ref":r,"kind":"SECTION","aspects":list(topics),"reason":"尚未展开的完整来源片段"} for r in expansions]
        if partial:out["caveats"].append("相关资料未全部展开，不可据此确认没有限制")
        if view=="CHANGES":
            v=self.session.get(ActivityKnowledgeVersion,vid)
            before=self.detail(rows[0].id,v.base_version_id) if v.base_version_id else None
            out["data"]["changes"]=[{"before_version_ref":str(v.base_version_id) if v.base_version_id else None,"after_version_ref":str(vid),
                                     "before":{"facts":before["facts"],"options":before["options"]} if before else None,"after":{"facts":detail["facts"],"options":detail["options"]}}]
        return out
