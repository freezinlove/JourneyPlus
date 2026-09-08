"""Reviewed public company-page identities, separate from official match facts."""
from sqlalchemy import select
from journeyplus.knowledge.models import MembershipProgram,MembershipTier
from journeyplus.knowledge.publication import canonical_key,display_tier_name

# Verified titles and report direction labels on 2026-09-07.
REVIEWED={
 'air-canada':{'names':['Air Canada Aeroplan','Air Canada'],'label':'Air Canada Aeroplan'},
 'vietnam-airlines':{'names':['Vietnam Airlines Lotusmiles','Lotusmiles (Vietnam Airlines)'],'label':'Vietnam Airlines Lotusmiles'},
 'royal-jordanian-airlines':{'names':['Royal Jordanian Royal Club','Royal Jordanian Airlines Royal Club'],'label':'Royal Jordanian Airlines Royal Club'},
}


def company_mappings(session):
    result={}
    tiers=list(session.scalars(select(MembershipTier)))
    for program in session.scalars(select(MembershipProgram)):
        for slug,reviewed in REVIEWED.items():
            if canonical_key(program.display_name) not in {canonical_key(n) for n in reviewed['names']}:continue
            identities={canonical_key(reviewed['label']):{'program_ref':str(program.id),'tier_ref':None}}
            tier_labels={}
            for tier in tiers:
                if tier.program_id!=program.id:continue
                from journeyplus.knowledge.catalog_identity import tier_label
                name=tier_label(program,tier.display_name)
                tier_labels[str(tier.id)]=name
                names=[name]
                if slug=='air-canada' and name.casefold().startswith('elite '):names.append(name[6:])
                for label in names:identities[canonical_key(reviewed['label']+' '+label)]={'program_ref':str(program.id),'tier_ref':str(tier.id)}
            result[str(program.id)]={'verified_url':'https://statusmatcher.com/company/'+slug,
                'verified_at':'2026-09-07','title':reviewed['label'],'identities':identities,'tier_labels':tier_labels}
    return result


def build_researcher(settings,factory):
    from journeyplus.agent.statusmatcher import StatusMatcherExperienceClient
    with factory() as session:mappings=company_mappings(session) if settings.statusmatcher_enabled else {}
    return StatusMatcherExperienceClient(enabled=settings.statusmatcher_enabled,
        timeout_seconds=settings.statusmatcher_timeout_seconds,max_response_bytes=settings.statusmatcher_max_response_bytes,
        max_pages=settings.statusmatcher_max_pages,company_mappings=mappings)
