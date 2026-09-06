from __future__ import annotations

import hashlib
import re
import json
import unicodedata
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from journeyplus.models import DocumentVersion, now_utc
from journeyplus.knowledge.contracts import KnowledgeDraft, SourceScope
from journeyplus.knowledge.models import (
    Activity, ActivityBrief, ActivityDocument, ActivityKnowledgeVersion, ApplicationOption,
    ApplicationOptionVersion, DocumentSection, EvidenceReference, MembershipAlias,
    MembershipProgram, MembershipTier, OptionMapping, OptionPrice, OptionPriceMapping,
)


def canonical_key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def display_tier_name(program, tier) -> str:
    name=tier.display_name
    if canonical_key(name).startswith(canonical_key(program.display_name)+' '):
        name=name[len(program.display_name):].strip()
    return re.sub(r'\s+status$','',name,flags=re.I)


def signature(value) -> str:
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",", ":"),default=str).encode()).hexdigest()


class StaleKnowledgeBase(ValueError):
    pass


class CatalogService:
    def __init__(self, session: Session):
        self.session = session

    def program(self, name: str, *, category: str = "OTHER", alliance: str | None = None) -> MembershipProgram:
        key = canonical_key(name)
        if not key:
            raise ValueError("Program name cannot be empty")
        row = self.session.scalar(select(MembershipProgram).where(MembershipProgram.canonical_key == key))
        if row is None:
            formatting_matches=[p for p in self.session.scalars(select(MembershipProgram)) if p.canonical_key.replace(' ','')==key.replace(' ','')]
            if len(formatting_matches)==1:
                row=formatting_matches[0]
                self.alias(name,row.id)
                return row
            row = MembershipProgram(canonical_key=key,display_name=name,category=category,alliance=alliance)
            self.session.add(row); self.session.flush()
        return row

    def tier(self, program_id: UUID, name: str) -> MembershipTier:
        key = canonical_key(name)
        if not key or self.session.get(MembershipProgram, program_id) is None:
            raise ValueError("Tier requires an existing program and name")
        row = self.session.scalar(select(MembershipTier).where(MembershipTier.program_id==program_id,MembershipTier.canonical_key==key))
        if row is None:
            program=self.session.get(MembershipProgram,program_id)
            def normalized_tier(value):
                value=canonical_key(value)
                if value.startswith(program.canonical_key+' '):value=value[len(program.canonical_key)+1:]
                return re.sub(r'\s+status$','',value)
            matches=[t for t in self.session.scalars(select(MembershipTier).where(MembershipTier.program_id==program_id)) if normalized_tier(t.canonical_key)==normalized_tier(key)]
            if len(matches)==1:
                self.alias(name,program_id,matches[0].id)
                return matches[0]
            row = MembershipTier(program_id=program_id,canonical_key=key,display_name=name)
            self.session.add(row); self.session.flush()
        return row

    def alias(self, name: str, program_id: UUID, tier_id: UUID | None = None):
        key = canonical_key(name)
        if tier_id and (tier := self.session.get(MembershipTier,tier_id)) and tier.program_id != program_id:
            raise ValueError("Alias tier belongs to another program")
        row = self.session.scalar(select(MembershipAlias).where(MembershipAlias.normalized_alias==key,
                                  MembershipAlias.program_id==program_id,MembershipAlias.tier_id==tier_id))
        if row is None:
            row=MembershipAlias(normalized_alias=key,program_id=program_id,tier_id=tier_id,origin="catalog")
            self.session.add(row);self.session.flush()
        return row

    def search(self, query: str, *, limit: int=20) -> dict:
        key=canonical_key(query)
        ids=set(self.session.scalars(select(MembershipAlias.program_id).where(MembershipAlias.normalized_alias.contains(key,autoescape=True))))
        rows=list(self.session.scalars(select(MembershipProgram).where(
            MembershipProgram.canonical_key.contains(key,autoescape=True) | MembershipProgram.id.in_(ids)
        ).order_by(MembershipProgram.canonical_key).limit(limit+1)))
        if not rows and key:
            compact=key.replace(' ','')
            matches=[]
            for p in self.session.scalars(select(MembershipProgram).order_by(MembershipProgram.canonical_key)):
                names=[p.canonical_key,*self.session.scalars(select(MembershipAlias.normalized_alias).where(MembershipAlias.program_id==p.id,MembershipAlias.tier_id.is_(None)))]
                if any(len(n.replace(' ',''))>=4 and n.replace(' ','') in compact for n in names):matches.append(p)
            rows=matches[:limit+1]
        return {"has_more":len(rows)>limit,"programs":[{"id":str(r.id),"name":r.display_name,"category":r.category,
                "tiers":[{"id":str(t.id),"name":t.display_name} for t in self.session.scalars(select(MembershipTier).where(MembershipTier.program_id==r.id).order_by(MembershipTier.canonical_key))]} for r in rows[:limit]]}


def _evidence_ids(value) -> set[UUID]:
    found=set()
    if isinstance(value,dict):
        for k,v in value.items():
            if k=="evidence_ids": found.update(UUID(str(x)) for x in v)
            else: found.update(_evidence_ids(v))
    elif isinstance(value,list):
        for item in value: found.update(_evidence_ids(item))
    return found


def _semantic(value):
    if isinstance(value,dict):
        return {k:_semantic(v) for k,v in value.items() if k != "evidence_ids" and
                not (k == "raw_text" and value.get("known_state") == "KNOWN")}
    if isinstance(value,list): return [_semantic(x) for x in value]
    return value


class PublicationService:
    """Pure database transaction work. Callers finish extraction/network before entry."""
    def __init__(self, session: Session):
        self.session=session

    def validate(self, draft: KnowledgeDraft):
        bindings={b.document_version_id:b for b in draft.documents}
        if len(bindings)!=len(draft.documents):
            raise ValueError("Duplicate source document binding")
        for docid,b in bindings.items():
            if self.session.get(DocumentVersion,docid) is None: raise ValueError("Missing source version")
            for sid in b.section_ids:
                s=self.session.get(DocumentSection,sid)
                if s is None or s.document_version_id!=docid: raise ValueError("Activity section belongs to another source")
        ids=_evidence_ids(draft.model_dump(mode="json"))
        for eid in ids:
            e=self.session.get(EvidenceReference,eid)
            if e is None or e.document_version_id not in bindings: raise ValueError("Evidence not bound to this activity version")
            scope=bindings[e.document_version_id].section_ids
            if e.precision!="SECTION" or (scope and e.section_id not in scope):
                raise ValueError("Published known facts need exact evidence within activity scope")
        def source(s:SourceScope):
            if s.program_id and self.session.get(MembershipProgram,s.program_id) is None: raise ValueError("Unknown source program")
            for tid in s.tier_ids:
                t=self.session.get(MembershipTier,tid)
                if t is None or t.program_id!=s.program_id: raise ValueError("Source tier/program mismatch")
        for option in draft.options:
            for price in option.prices:
                if price.known_state != "KNOWN":continue
                quotes="\n".join(self.session.get(EvidenceReference,e).quote for e in price.evidence_ids)
                if price.amount == 0:
                    if not re.search(r"no\s+(?:application\s+)?fee|no\s+fee\s+payable|free\s+of\s+charge|免(?:申请)?费|不收取.*费用",quotes,re.I):
                        raise ValueError("Zero fee lacks explicit free application evidence")
                else:
                    if price.raw_text not in quotes:
                        raise ValueError("Known price raw_text must be an exact supporting source excerpt")
                    quotes=price.raw_text
                    targets={m.target_tier_id for m in option.mappings}
                    if len(targets)>1 and price.target_scope=='EXACT':
                        tier=self.session.get(MembershipTier,price.target_tier_id)
                        program=self.session.get(MembershipProgram,tier.program_id)
                        label=tier.display_name
                        if canonical_key(label).startswith(program.canonical_key+' '):label=label[len(program.display_name)+1:]
                        label=re.sub(r'\s+status$','',label,flags=re.I)
                        if not re.search(r'(?<!\w)'+re.escape(label)+r'(?!\w)',quotes,re.I):
                            raise ValueError("Multi-target price excerpt does not identify its target tier")
                    if len(targets)>1 and price.target_scope=='ALL_TARGETS' and not re.search(r'all\s+(?:tiers|levels)|flat\s+fee|所有.*等级|统一.*费',quotes,re.I):
                        raise ValueError("Universal nonzero fee lacks explicit all-target evidence")
                    amount=format(price.amount.normalize(),'f')
                    if not re.search(r"(?<![\d.])"+re.escape(amount)+r"(?:\.0+)?(?!\d|\.\d)",quotes.replace(',','')):
                        raise ValueError("Known amount is absent from its source evidence")
                    currencies={'EUR':['EUR','€'],'USD':['USD','US$'],'GBP':['GBP','£']}
                    if not any(token.casefold() in quotes.casefold() for token in currencies.get(price.currency,[price.currency])):
                        raise ValueError("Known currency is absent from its source evidence")
            source(option.source_scope)
            parent_ids={c.condition_id for c in draft.facts.conditions.items}
            for group in [option.conditions,*[m.conditions for m in option.mappings],*[p.conditions for p in option.prices]]:
                for c in group.items:
                    if not set(c.supersedes_ids)<=parent_ids: raise ValueError("Condition overrides unknown parent")
                if group is option.conditions: parent_ids|={c.condition_id for c in group.items}
            for mapping in option.mappings:
                source(mapping.source_scope)
                t=self.session.get(MembershipTier,mapping.target_tier_id)
                if t is None or t.program_id!=mapping.target_program_id: raise ValueError("Target tier/program mismatch")
                parent=option.source_scope;child=mapping.source_scope
                if parent.kind=="EXACT_TIERS" and (child.kind!="EXACT_TIERS" or child.program_id!=parent.program_id or not set(child.tier_ids)<=set(parent.tier_ids)):
                    raise ValueError("Mapping widens option source scope")
                if parent.kind=="PROGRAM_ANY_TIER" and (child.kind not in {"EXACT_TIERS","PROGRAM_ANY_TIER"} or child.program_id!=parent.program_id):
                    raise ValueError("Mapping widens option program scope")
        return ids

    def publish(self, draft: KnowledgeDraft) -> ActivityKnowledgeVersion:
        self.validate(draft)
        a=self.session.scalar(select(Activity).where(Activity.id==draft.activity_id).with_for_update())
        if a is None: raise LookupError("Activity does not exist")
        old=self.session.scalar(select(ActivityKnowledgeVersion).where(ActivityKnowledgeVersion.activity_id==a.id,
                                ActivityKnowledgeVersion.extraction_key==draft.extraction_key))
        payload=draft.model_dump(mode="json")
        fact_hash=signature(_semantic({"facts":payload["facts"],"options":payload["options"]}))
        source_hash=signature({"documents":payload["documents"],"evidence":sorted(map(str,_evidence_ids(payload)))})
        if old:
            if old.fact_hash!=fact_hash or old.source_hash!=source_hash: raise ValueError("Extraction key reused with different content")
            return old
        if a.current_version_id!=draft.base_version_id: raise StaleKnowledgeBase("Activity changed during extraction; rebase and validate")
        previous=self.session.get(ActivityKnowledgeVersion,a.current_version_id) if a.current_version_id else None
        if previous and previous.fact_hash==fact_hash and previous.source_hash==source_hash:
            return previous
        number=(self.session.scalar(select(func.max(ActivityKnowledgeVersion.version_no)).where(ActivityKnowledgeVersion.activity_id==a.id)) or 0)+1
        v=ActivityKnowledgeVersion(activity_id=a.id,version_no=number,base_version_id=draft.base_version_id,
                                  status="VALIDATED",facts=payload["facts"],fact_hash=fact_hash,source_hash=source_hash,extraction_key=draft.extraction_key)
        self.session.add(v);self.session.flush()
        for b in draft.documents:
            self.session.add(ActivityDocument(knowledge_version_id=v.id,document_version_id=b.document_version_id,role=b.role,section_scope=list(map(str,b.section_ids))))
        self.session.flush()
        for o in draft.options:
            identity=self.session.scalar(select(ApplicationOption).where(ApplicationOption.activity_id==a.id,ApplicationOption.logical_key==o.logical_key))
            if identity is None:
                identity=ApplicationOption(activity_id=a.id,logical_key=o.logical_key)
                self.session.add(identity);self.session.flush()
            data=o.model_dump(mode="json",exclude={"logical_key","mappings","prices"})
            ov=ApplicationOptionVersion(activity_id=a.id,knowledge_version_id=v.id,option_id=identity.id,**data)
            self.session.add(ov);self.session.flush()
            mappings={}
            for m in o.mappings:
                data=m.model_dump(mode="json",exclude={"key","target_program_id","target_tier_id"})
                row=OptionMapping(option_version_id=ov.id,knowledge_version_id=v.id,semantic_key=m.key,
                                  target_program_id=m.target_program_id,target_tier_id=m.target_tier_id,**data)
                self.session.add(row);self.session.flush();mappings[m.key]=row.id
            for p in o.prices:
                data=p.model_dump(mode="json",exclude={"key","mapping_keys","target_tier_id","amount"})
                row=OptionPrice(option_version_id=ov.id,knowledge_version_id=v.id,price_key=p.key,
                                target_tier_id=p.target_tier_id,amount=p.amount,**data)
                self.session.add(row);self.session.flush()
                for key in p.mapping_keys:
                    self.session.add(OptionPriceMapping(price_id=row.id,mapping_id=mappings[key],option_version_id=ov.id))
                self.session.flush()
        v.status="PUBLISHED";v.published_at=now_utc();self.session.flush()
        a.current_version_id=v.id;self.session.flush()
        self.session.add(ActivityBrief(knowledge_version_id=v.id,brief_kind="CURRENT",generator_version="knowledge-1"))
        if previous and previous.fact_hash!=fact_hash:
            self.session.add(ActivityBrief(knowledge_version_id=v.id,previous_version_id=previous.id,brief_kind="UPDATE",generator_version="knowledge-1"))
        self.session.flush()
        return v
