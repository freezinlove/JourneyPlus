"""Link existing user-confirmed labels only to uniquely identified catalogue rows."""
from sqlalchemy import select
from journeyplus.models import StatusHolding
from journeyplus.knowledge.models import MembershipProgram,MembershipTier,MembershipAlias
from journeyplus.membership.normalization import normalize_key


def backfill_holding_links(session):
    programs=list(session.scalars(select(MembershipProgram)));aliases=list(session.scalars(select(MembershipAlias)))
    report={'mapped':[],'unchanged':[],'unresolved':[]}
    for holding in session.scalars(select(StatusHolding)):
        if holding.program_id and holding.tier_id and holding.identity_status=='CONFIRMED':report['unchanged'].append(str(holding.id));continue
        name=normalize_key(holding.program_display_name)
        ids={p.id for p in programs if normalize_key(p.display_name)==name}
        ids.update(a.program_id for a in aliases if a.tier_id is None and normalize_key(a.normalized_alias)==name)
        if len(ids)!=1:report['unresolved'].append({'holding_ref':str(holding.id),'reason':'PROGRAM_MISSING_OR_AMBIGUOUS'});continue
        pid=next(iter(ids));label=normalize_key(holding.tier_display_name)
        tiers={t.id for t in session.scalars(select(MembershipTier).where(MembershipTier.program_id==pid)) if normalize_key(t.display_name)==label}
        tiers.update(a.tier_id for a in aliases if a.program_id==pid and a.tier_id and normalize_key(a.normalized_alias)==label)
        if len(tiers)!=1:report['unresolved'].append({'holding_ref':str(holding.id),'reason':'TIER_MISSING_OR_AMBIGUOUS'});continue
        holding.program_id=pid;holding.tier_id=next(iter(tiers));holding.identity_status='CONFIRMED';holding.revision+=1
        from journeyplus.knowledge.migration import _link
        _link(session,'status_holdings',holding.id,'','status_holdings',holding.id,'MAPPED','Unique existing catalogue identity; original confirmed labels and expiry preserved')
        report['mapped'].append(str(holding.id))
    session.flush();return report
