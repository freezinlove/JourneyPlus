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


def price_tier_labels(program, tier, quote):
    labels={canonical_key(tier.display_name),canonical_key(display_tier_name(program,tier))}
    for cell in quote.split('|'):
        cell=re.sub(r'[*_`]','',cell).strip()
        match=re.fullmatch(r'(.+?)\s+(?:tier|status)',cell,re.I)
        if match:
            qualifier=canonical_key(match[1])
            from collections import Counter
            same_program_words=Counter(re.findall(r'\w+',qualifier))==Counter(re.findall(r'\w+',program.canonical_key))
            if same_program_words or re.search(r'(?<!\w)'+re.escape(qualifier)+r'(?!\w)',program.canonical_key):
                for label in tuple(labels):
                    if label.startswith(qualifier+' '):labels.add(label[len(qualifier)+1:])
    return labels


def explicit_target_amounts(program, tier, quote, currency):
    """Read only explicit two-cell rows or 'money for target' clauses."""
    from decimal import Decimal
    labels=price_tier_labels(program,tier,quote)
    currencies={'USD':['USD','US$'],'EUR':['EUR','€'],'GBP':['GBP','£']}.get(currency,[currency])
    prefix='(?:'+'|'.join(re.escape(c) for c in currencies if c)+')'
    if currency=='USD' and not re.search(r'\b(?:CAD|AUD|NZD|SGD|HKD|EUR|GBP|JPY)\b|[€£¥]',quote,re.I):
        prefix=r'(?:'+prefix+r'\s*\$?|\$)'
    number=r'([0-9][0-9,]*(?:\.[0-9]+)?)'
    amounts=set()
    for label in labels:
        for match in re.finditer(prefix+r'\s*'+number+r'\s+for\s+(?:the\s+)?'+re.escape(label)+r'(?!\w)',quote,re.I):
            amounts.add(Decimal(match[1].replace(',','')))
    for line in quote.splitlines():
        cells=[re.sub(r'[*_`]','',c).strip() for c in line.strip().strip('|').split('|')]
        if '|' not in line or len(cells)!=2 or canonical_key(cells[0]) not in labels:continue
        match=re.fullmatch(prefix+r'\s*'+number,cells[1],re.I)
        if match is None:match=re.fullmatch(number+r'\s*'+prefix,cells[1],re.I)
        if match:amounts.add(Decimal(match[1].replace(',','')))
    return amounts


def document_holder_clause(raw):
    return bool(re.search(r'identity document holders|passport holders',raw,re.I)) and not re.search(
        r'\bresidents?\b|\bresidency\b|\bresid(?:e|ing)\b|\bliv(?:e|ing)\b',raw,re.I)


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
        from journeyplus.knowledge.catalog_identity import REVIEWED_PROGRAM_SPELLINGS,program_key
        if key in REVIEWED_PROGRAM_SPELLINGS:
            candidates=[p for p in self.session.scalars(select(MembershipProgram)) if program_key(p)==REVIEWED_PROGRAM_SPELLINGS[key]]
            primary_ids=set(self.session.scalars(select(Activity.primary_program_id).where(Activity.merged_into_id.is_(None))))
            preferred=[p for p in candidates if p.id in primary_ids]
            if len(preferred)==1 or len(candidates)==1:
                row=(preferred or candidates)[0]
                self.alias(name,row.id)
                return row
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
        from journeyplus.knowledge.catalog_identity import tier_label
        program=self.session.get(MembershipProgram,program_id)
        spelling_matches=[t for t in self.session.scalars(select(MembershipTier).where(MembershipTier.program_id==program_id))
                          if tier_label(program,t.display_name)==tier_label(program,name)]
        if spelling_matches:
            row=min(spelling_matches,key=lambda t:(len(t.display_name),str(t.id)))
            if canonical_key(row.display_name)!=key:self.alias(name,program_id,row.id)
            return row
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
        if not key or self.session.get(MembershipProgram,program_id) is None:
            raise ValueError("Alias requires a nonempty name and existing program")
        if tier_id:
            tier=self.session.get(MembershipTier,tier_id)
            if tier is None or tier.program_id != program_id:
                raise ValueError("Alias tier belongs to another program or does not exist")
        row = self.session.scalar(select(MembershipAlias).where(MembershipAlias.normalized_alias==key,
                                  MembershipAlias.program_id==program_id,MembershipAlias.tier_id==tier_id))
        if row is None:
            row=MembershipAlias(normalized_alias=key,program_id=program_id,tier_id=tier_id,origin="catalog")
            self.session.add(row);self.session.flush()
        return row

    def search(self, query: str, *, limit: int=20) -> dict:
        if not 1 <= limit <= 50:raise ValueError('Catalog limit must be between 1 and 50')
        key=canonical_key(query)
        ids=set(self.session.scalars(select(MembershipAlias.program_id).where(MembershipAlias.normalized_alias.contains(key,autoescape=True))))
        rows=list(self.session.scalars(select(MembershipProgram).where(
            MembershipProgram.canonical_key.contains(key,autoescape=True) | MembershipProgram.id.in_(ids)
        ).order_by(MembershipProgram.canonical_key).limit(limit+1)))
        if not rows and key:
            # Distinctive full tier labels can locate a program without guessing
            # an unregistered acronym. Generic Gold/Silver labels never do so.
            tier_programs=set()
            generic={'gold','silver','platinum','status','elite','tier','club'}
            for tier in self.session.scalars(select(MembershipTier)):
                label=tier.canonical_key
                words=set(label.split())
                if len(words)>=2 and words-generic and re.search(r'(?<!\w)'+re.escape(label)+r'(?!\w)',key):
                    tier_programs.add(tier.program_id)
            if tier_programs:
                rows=list(self.session.scalars(select(MembershipProgram).where(MembershipProgram.id.in_(tier_programs)).order_by(MembershipProgram.canonical_key).limit(limit+1)))
        if not rows and key:
            compact=key.replace(' ','')
            matches=[];aliases={}
            for program_id,alias in self.session.execute(select(MembershipAlias.program_id,MembershipAlias.normalized_alias).where(MembershipAlias.tier_id.is_(None))):
                aliases.setdefault(program_id,[]).append(alias)
            for p in self.session.scalars(select(MembershipProgram).order_by(MembershipProgram.canonical_key)):
                names=[p.canonical_key,*aliases.get(p.id,[])]
                if any(len(n.replace(' ',''))>=4 and n.replace(' ','') in compact for n in names):matches.append(p)
            rows=matches[:limit+1]
        from journeyplus.knowledge.catalog_identity import program_key,tier_label
        grouped={};program_tiers={}
        primary_ids=set(self.session.scalars(select(Activity.primary_program_id).where(Activity.merged_into_id.is_(None))))
        for row in rows:
            unique={}
            for tier in sorted(self.session.scalars(select(MembershipTier).where(MembershipTier.program_id==row.id)),key=lambda t:(len(t.display_name),str(t.id))):
                unique.setdefault(tier_label(row,tier.display_name),tier)
            program_tiers[row.id]=unique
            # Never drop tiers unique to one historical catalogue record.
            grouping=(program_key(row),tuple(sorted(unique)))
            prior=grouped.get(grouping)
            if prior is None or row.id in primary_ids and prior.id not in primary_ids:grouped[grouping]=row
        more=len(rows)>limit
        rows=list(grouped.values())
        return {"has_more":more,"programs":[{"id":str(r.id),"name":r.display_name,"category":r.category,
                "tiers":[{"id":str(t.id),"name":t.display_name} for t in program_tiers[r.id].values()]} for r in rows[:limit]]}


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

    def ground_condition_topics(self,draft:KnowledgeDraft)->KnowledgeDraft:
        """Correct only explicitly evidenced document-holder clauses.

        Holding an identity document issued by a country does not establish
        residency in that country. Keep the full clause as an unevaluated
        document requirement, never manufacture a nationality/region filter.
        """
        data=draft.model_dump(mode='json')
        groups=[data['facts'].get('conditions',{})]
        for option in data['options']:
            groups.extend([option.get('conditions',{}),*[m.get('conditions',{}) for m in option['mappings']],*[p.get('conditions',{}) for p in option['prices']]])
        for group in groups:
            for condition in group.get('items',[]):
                raw=condition.get('raw_text','')
                if condition.get('known_state')!='KNOWN' or condition.get('topic')!='RESIDENCY' or not document_holder_clause(raw):continue
                quotes=[self.session.get(EvidenceReference,UUID(ref)) for ref in condition.get('evidence_ids',[])]
                pattern=r'\s+'.join(re.escape(word) for word in raw.split())
                matches={m.group(0) for e in quotes if e for m in re.finditer(pattern,e.quote)}
                if len(matches)==1:
                    literal=matches.pop()
                    condition.update(topic='DOCUMENT_REQUIREMENT',operator='TEXT',value=literal,raw_text=literal)
        return KnowledgeDraft.model_validate(data)

    def ground_simple_price_rows(self, draft: KnowledgeDraft) -> KnowledgeDraft:
        """Resolve only unambiguous two-cell target/application-fee table rows.

        The model selects a target and amount; the server retains the literal row.
        Never infer regions, multi-column alternatives or totals from this helper.
        """
        data=draft.model_dump(mode='json')
        for option in data['options']:
            for price in option['prices']:
                if price['known_state']=='KNOWN' and price.get('raw_text'):
                    # Recover literal typography only, never change words/numbers.
                    parts=re.split(r'(\s+|[-–—])',price['raw_text'])
                    pattern=''.join(r'\s+' if p.isspace() else r'[-–—]' if p in {'-','–','—'} else re.escape(p) for p in parts)
                    matches=set()
                    for eid in price['evidence_ids']:
                        evidence=self.session.get(EvidenceReference,UUID(eid))
                        if evidence:
                            matches.update(m.group(0) for m in re.finditer(pattern,evidence.quote,re.I))
                    if len(matches)==1:price['raw_text']=matches.pop()
                if price['known_state']!='KNOWN' or price['target_scope']!='EXACT' or price['fee_role']!='APPLICATION' or not price['amount']:
                    continue
                tier=self.session.get(MembershipTier,UUID(price['target_tier_id']))
                if tier is None:continue
                program=self.session.get(MembershipProgram,tier.program_id)
                labels={canonical_key(tier.display_name),canonical_key(display_tier_name(program,tier))}
                from decimal import Decimal
                amount=format(Decimal(price['amount']).normalize(),'f')
                currencies={'USD':['USD','US$'],'EUR':['EUR','€'],'GBP':['GBP','£']}.get(price['currency'],[price['currency']])
                currencies=[c for c in currencies if c]
                number=re.escape(amount)+r'(?:\.0+)?'
                currency='(?:'+'|'.join(re.escape(c) for c in currencies)+')'
                money=re.compile(r'^(?:'+currency+r'\s*'+number+'|'+number+r'\s*'+currency+r')$',re.I)
                candidates=set()
                for eid in price['evidence_ids']:
                    evidence=self.session.get(EvidenceReference,UUID(eid))
                    if evidence is None:continue
                    labels=price_tier_labels(program,tier,evidence.quote)
                    from journeyplus.knowledge.regional_prices import regional_fee_rows,region_scope_matches
                    regional=[row for row in regional_fee_rows(evidence.quote) if canonical_key(row['tier']) in labels
                              and row['currency']==price['currency'] and row['amount']==Decimal(price['amount'])
                              and region_scope_matches(row,option,price)]
                    if len(regional)==1:
                        # Keep the full table: a blank country cell inherits its
                        # preceding region, and qualifications stay attached.
                        candidates.add(evidence.quote)
                    # A priced clause such as "$49 for the Silver Jay tier" can
                    # identify a target without a table. Retain the entire original
                    # sentence, including other tiers and its qualifications.
                    for sentence in re.split(r'(?<=\.)\s+|\n\s*\n',evidence.quote):
                        if not re.search(r'\b(?:fees?|price|cost|payment)\b',sentence,re.I):continue
                        money_prefix=currency
                        if price['currency']=='USD' and not re.search(r'\b(?:CAD|AUD|NZD|SGD|HKD|EUR|GBP|JPY)\b|[€£¥]',sentence,re.I):
                            money_prefix=r'(?:'+currency+r'\s*\$?|\$)'
                        if any(re.search(money_prefix+r'\s*'+number+r'\s+for\s+(?:the\s+)?'+re.escape(label)+r'(?!\w)',sentence,re.I) for label in labels):
                            candidates.add(sentence.strip())
                    for line in evidence.quote.splitlines():
                        cells=[re.sub(r'[*_`]','',c).strip() for c in line.strip().strip('|').split('|')]
                        if '|' not in line or len(cells)!=2:continue
                        if canonical_key(cells[0]) in labels and money.fullmatch(cells[1].replace(',','')):
                            candidates.add(line)
                if len(candidates)==1:price['raw_text']=next(iter(candidates))
        return KnowledgeDraft.model_validate(data)

    def validate(self, draft: KnowledgeDraft):
        condition_groups=[draft.facts.conditions]
        for option in draft.options:
            condition_groups.extend([option.conditions,*[m.conditions for m in option.mappings],*[p.conditions for p in option.prices]])
        if any(c.known_state=='KNOWN' and c.topic=='RESIDENCY' and document_holder_clause(c.raw_text)
               for group in condition_groups for c in group.items):
            raise ValueError('Document-holder condition is misclassified as residency; ground or repair before publication')
        bindings={b.document_version_id:b for b in draft.documents}
        if len(bindings)!=len(draft.documents):
            raise ValueError("Duplicate source document binding")
        for docid,b in bindings.items():
            if self.session.get(DocumentVersion,docid) is None: raise ValueError("Missing source version")
            from journeyplus.knowledge.sources import require_knowledge_content
            require_knowledge_content(self.session.get(DocumentVersion,docid))
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
            if s.kind=='CATEGORY_RULE' and s.category in {'AIRLINE','HOTEL','CRUISE'}:
                # A finite eligibility table cannot authorize every program in a
                # category. Unproven categories stay draft/UNKNOWN until expanded.
                quotes='\n'.join(self.session.get(EvidenceReference,e).quote for e in s.evidence_ids)
                nouns={'AIRLINE':r'airlines?|airline\s+(?:loyalty\s+)?programs?',
                       'HOTEL':r'hotels?|hotel\s+(?:loyalty\s+)?programs?',
                       'CRUISE':r'cruise\s+(?:lines?|programs?)'}
                pattern=r'\b(?:all|any|every)\s+(?:major\s+)?(?:'+nouns[s.category]+r')\b'
                if not re.search(pattern,re.sub(r'[*_]','',quotes),re.I):
                    raise ValueError('Category source lacks explicit broad-category evidence; expand the eligible table into exact mappings')
            if s.program_id and self.session.get(MembershipProgram,s.program_id) is None: raise ValueError("Unknown source program")
            for tid in s.tier_ids:
                t=self.session.get(MembershipTier,tid)
                if t is None or t.program_id!=s.program_id: raise ValueError("Source tier/program mismatch")
        for option in draft.options:
            # Scope errors determine whether an option exists at all. Surface
            # them before fee details so the bounded repair fixes the root issue.
            source(option.source_scope)
            for mapping in option.mappings:source(mapping.source_scope)
            for price in option.prices:
                if price.known_state != "KNOWN":continue
                quotes="\n".join(self.session.get(EvidenceReference,e).quote for e in price.evidence_ids)
                if price.amount == 0:
                    if not re.search(r"no\s+(?:application\s+)?fee|no\s+fee\s+payable|free\s+of\s+charge|免(?:申请)?费|不收取.*费用",quotes,re.I):
                        raise ValueError("Zero fee lacks explicit free application evidence")
                else:
                    if price.raw_text not in quotes:
                        raise ValueError(f"Known price raw_text must be an exact supporting source excerpt: price={price.key}, raw_text={price.raw_text!r}")
                    quotes=price.raw_text
                    targets={m.target_tier_id for m in option.mappings}
                    if price.target_scope=='EXACT':
                        tier=self.session.get(MembershipTier,price.target_tier_id)
                        if tier is None:raise ValueError('Unknown price target tier')
                        program=self.session.get(MembershipProgram,tier.program_id)
                        evidence_quote='\n'.join(self.session.get(EvidenceReference,e).quote for e in price.evidence_ids)
                        labels=price_tier_labels(program,tier,evidence_quote)
                        from journeyplus.knowledge.regional_prices import regional_fee_rows,region_scope_matches
                        regional=regional_fee_rows(evidence_quote)
                        if regional and not any(canonical_key(row['tier']) in labels and row['currency']==price.currency
                            and row['amount']==price.amount and region_scope_matches(row,option.model_dump(mode='json'),price.model_dump(mode='json')) for row in regional):
                            raise ValueError('Regional price does not match target, currency, region or exclusion')
                        paired=explicit_target_amounts(program,tier,evidence_quote,price.currency)
                        if paired and price.amount not in paired:
                            raise ValueError(f'Price amount disagrees with explicit target association: price={price.key}, target={tier.display_name}')
                        if len(targets)>1 and not any(re.search(r'(?<!\w)'+re.escape(label)+r'(?!\w)',quotes,re.I) for label in labels):
                            raise ValueError(f"Multi-target price excerpt does not identify its target tier: price={price.key}, target={tier.display_name}")
                    if len(targets)>1 and price.target_scope=='ALL_TARGETS' and not re.search(r'all\s+(?:tiers|levels|applicants)|(?:each|every)\s+application|flat\s+fee|所有.*等级|所有申请人|统一.*费',quotes,re.I):
                        raise ValueError("Universal nonzero fee lacks explicit all-target evidence")
                    amount=format(price.amount.normalize(),'f')
                    if not re.search(r"(?<![\d.])"+re.escape(amount)+r"(?:\.0+)?(?!\d|\.\d)",quotes.replace(',','')):
                        raise ValueError("Known amount is absent from its source evidence")
                    currencies={'EUR':['EUR','€'],'USD':['USD','US$'],'GBP':['GBP','£']}
                    if not any(token.casefold() in quotes.casefold() for token in currencies.get(price.currency,[price.currency])):
                        raise ValueError("Known currency is absent from its source evidence")
            parent_ids={c.condition_id for c in draft.facts.conditions.items}
            parent_conditions={c.condition_id:c for c in draft.facts.conditions.items}
            for group in [option.conditions,*[m.conditions for m in option.mappings],*[p.conditions for p in option.prices]]:
                for c in group.items:
                    if not set(c.supersedes_ids)<=parent_ids: raise ValueError("Condition overrides unknown parent")
                    if c.condition_id in parent_conditions and c!=parent_conditions[c.condition_id] and c.condition_id not in c.supersedes_ids:
                        raise ValueError('Condition reuses a parent identifier without an explicit override')
                if group is option.conditions:
                    parent_ids|={c.condition_id for c in group.items}
                    parent_conditions.update({c.condition_id:c for c in group.items})
            for mapping in option.mappings:
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
        if a.merged_into_id is not None:
            raise StaleKnowledgeBase("Activity was merged; resolve its identity and prepare again")
        old=self.session.scalar(select(ActivityKnowledgeVersion).where(ActivityKnowledgeVersion.activity_id==a.id,
                                ActivityKnowledgeVersion.extraction_key==draft.extraction_key))
        payload=draft.model_dump(mode="json")
        semantic={"facts":payload["facts"],"options":payload["options"]}
        if payload.get('validation_notes'):semantic['validation_notes']=payload['validation_notes']
        fact_hash=signature(_semantic(semantic))
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
                                  status="VALIDATED",facts=payload["facts"],fact_hash=fact_hash,source_hash=source_hash,extraction_key=draft.extraction_key,
                                  validation_errors=payload.get('validation_notes',[]))
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
