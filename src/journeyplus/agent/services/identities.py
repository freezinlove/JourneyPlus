"""Deterministic name-to-record binding; ambiguity is data, never a question."""
import unicodedata
import re
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import load_only
from journeyplus.knowledge.models import MembershipProgram, MembershipTier, MembershipAlias


def canonical(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


class IdentityService:
    def resolve(self, session, identity, *, require_tier=False, context=None):
        value = identity.model_dump(exclude_none=True) if hasattr(identity, 'model_dump') else identity
        if value.get('ref','').startswith('artifact:'):
            if context is None:return {'status':'NOT_FOUND','code':'STALE_REFERENCE','candidates':[]}
            record=context.artifact_port.read(context.workspace_id,value['ref'])
            payload=record['payload'];payload=payload.get('data',payload)
            candidates=payload.get('holdings',payload.get('candidates',[payload]))
            values=[]
            for candidate in candidates:
                reference=candidate.get('tier_ref') or candidate.get('program_ref') or candidate.get('ref','')
                if reference.startswith(('program:','tier:')):values.append({'ref':reference})
                elif candidate.get('program_name'):
                    values.append({key:candidate[key] for key in ('program_name','tier_name') if candidate.get(key)})
            if len(values)!=1:
                return {'status':'AMBIGUOUS' if values else 'NOT_FOUND','code':'IDENTITY_AMBIGUOUS' if values else 'STALE_REFERENCE','candidates':values[:10]}
            value=values[0]
        # A typed reference needs two indexed reads, not three directory scans.
        reference=value.get('ref','')
        kind,separator,raw=reference.partition(':')
        if reference and kind in {'tier','program'}:
            try:identity_id=UUID(raw)
            except ValueError:return {'status':'NOT_FOUND','code':'STALE_REFERENCE','candidates':[]}
            tier=session.get(MembershipTier,identity_id) if kind=='tier' else None
            program=session.get(MembershipProgram,tier.program_id if tier else identity_id) if kind=='program' or tier else None
            if program is None:return {'status':'NOT_FOUND','code':'CATALOG_GAP','candidates':[]}
            if require_tier and tier is None:
                tiers=session.scalars(select(MembershipTier).where(MembershipTier.program_id==program.id).order_by(MembershipTier.id).limit(10))
                return {'status':'AMBIGUOUS','code':'IDENTITY_AMBIGUOUS','program':self.view(program),
                        'candidates':[self.view(program,item) for item in tiers]}
            return {'status':'OK',**self.view(program,tier)}
        # The remaining Unicode/alias matching shares one narrow catalogue within
        # this read transaction. No global cache can hide later catalogue edits.
        cached=session.info.get('agent_identity_catalog')
        catalog=cached[1] if cached and cached[0] is session.get_transaction() and not (session.new or session.dirty or session.deleted) else None
        if catalog is None:
            catalog=(
                {p.id:p for p in session.scalars(select(MembershipProgram).options(load_only(
                    MembershipProgram.id,MembershipProgram.display_name,MembershipProgram.canonical_key,
                    MembershipProgram.category,MembershipProgram.alliance)))},
                {t.id:t for t in session.scalars(select(MembershipTier).options(load_only(
                    MembershipTier.id,MembershipTier.program_id,MembershipTier.display_name,MembershipTier.canonical_key)))},
                list(session.scalars(select(MembershipAlias).options(load_only(
                    MembershipAlias.program_id,MembershipAlias.tier_id,MembershipAlias.normalized_alias)))))
            session.info['agent_identity_catalog']=(session.get_transaction(),catalog)
        programs,tiers,aliases=catalog
        selected = []
        tier = None
        if value.get('ref'):
            ref = value['ref']
            kind, sep, raw = ref.partition(':')
            try:
                key = UUID(raw if sep else ref)
            except ValueError:
                return {'status':'NOT_FOUND','code':'STALE_REFERENCE','candidates':[]}
            if kind=='tier' or not sep and key in tiers:
                tier = tiers.get(key)
                selected = [programs[tier.program_id]] if tier else []
            elif kind=='program' or not sep:
                selected = [programs[key]] if key in programs else []
        else:
            names = {canonical(n) for n in [value['program_name'], *value.get('alternatives', [])]}
            ids = {p.id for p in programs.values() if canonical(p.display_name) in names or canonical(p.canonical_key) in names}
            ids |= {a.program_id for a in aliases if a.tier_id is None and canonical(a.normalized_alias) in names}
            if not ids:
                candidates = [p for p in programs.values() if any(
                       len(name)>=3 and re.fullmatch(r'[a-z0-9 &+.-]+',name)
                       and re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',canonical(p.display_name))
                       for name in names)]
                if candidates:
                    return {'status':'NOT_FOUND','code':'CATALOG_GAP',
                            'candidates':[{**self.view(p),'match_basis':'whole_phrase_candidate'} for p in candidates][:10]}
            selected = [programs[i] for i in ids]
            if not selected:
                candidates = [self.view(p) for p in programs.values() if any(n in canonical(p.display_name) or canonical(p.display_name) in n for n in names)]
                return {'status':'NOT_FOUND','code':'CATALOG_GAP','candidates':candidates[:10]}
        if len(selected)!=1:
            return {'status':'AMBIGUOUS' if selected else 'NOT_FOUND', 'code':'IDENTITY_AMBIGUOUS' if selected else 'CATALOG_GAP', 'candidates':[self.view(p) for p in selected][:10]}
        program = selected[0]
        if tier is None and value.get('tier_name'):
            name = canonical(value['tier_name'])
            matches = {t.id for t in tiers.values() if t.program_id==program.id and name in {canonical(t.display_name), canonical(t.canonical_key)}}
            matches |= {a.tier_id for a in aliases if a.program_id==program.id and a.tier_id and canonical(a.normalized_alias)==name}
            if len(matches)==1:
                tier=tiers[next(iter(matches))]
            else:
                return {'status':'AMBIGUOUS' if matches else 'NOT_FOUND','code':'IDENTITY_AMBIGUOUS' if matches else 'CATALOG_GAP',
                        'program':self.view(program),'candidates':[self.view(program,t) for t in tiers.values() if t.program_id==program.id][:10]}
        if require_tier and tier is None:
            return {'status':'AMBIGUOUS','code':'IDENTITY_AMBIGUOUS','program':self.view(program),
                    'candidates':[self.view(program,t) for t in tiers.values() if t.program_id==program.id][:10]}
        return {'status':'OK',**self.view(program,tier)}

    @staticmethod
    def view(program,tier=None):
        return {'ref':('tier:'+str(tier.id)) if tier else 'program:'+str(program.id),
                'program_ref':'program:'+str(program.id),'tier_ref':'tier:'+str(tier.id) if tier else None,
                'program_name':program.display_name,'tier_name':tier.display_name if tier else None,
                'category':program.category,'alliance':program.alliance}
