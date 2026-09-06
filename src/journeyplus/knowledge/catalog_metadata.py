"""Audited catalogue enrichment from exact reviewed aliases and official text."""
import re
from sqlalchemy import select
from journeyplus.knowledge.models import MembershipProgram,Activity,ActivityDocument
from journeyplus.models import DocumentVersion
from journeyplus.knowledge.publication import canonical_key
from journeyplus.membership.alliances import exact_airline_alliance,ALLIANCE_DIRECTORY_AS_OF,ALLIANCE_DIRECTORY_SOURCES


def sync_catalog_metadata(session,program_ids=None):
    updated=[];conflicts=[]
    query=select(MembershipProgram).order_by(MembershipProgram.id)
    if program_ids is not None:query=query.where(MembershipProgram.id.in_(program_ids))
    for program in session.scalars(query):
        from journeyplus.knowledge.catalog_identity import program_key
        alliance=exact_airline_alliance(program.display_name) or exact_airline_alliance(program_key(program))
        category=None;provenance=None
        if alliance:
            category='AIRLINE';provenance={'origin':'EXACT_REVIEWED_ALLIANCE_ALIAS','as_of':ALLIANCE_DIRECTORY_AS_OF,'url':ALLIANCE_DIRECTORY_SOURCES[alliance]}
        else:
            # Only a statement about the TARGET frequent-flyer programme, never
            # the accepted airline/hotel source members or generic page footer.
            documents=session.scalars(select(DocumentVersion).join(ActivityDocument,ActivityDocument.document_version_id==DocumentVersion.id).join(Activity,Activity.current_version_id==ActivityDocument.knowledge_version_id).where(Activity.primary_program_id==program.id,ActivityDocument.role=='OFFICIAL_SUPPORT',DocumentVersion.canonical_url.endswith('/faq')))
            for document in documents:
                text=' '.join(document.normalized_body.split())
                for match in re.finditer(r'equivalent frequent flyer status in (?:the )?(.{1,100}?) (?:program|programme)\b',text,re.I):
                    target=canonical_key(match[1]);name=canonical_key(program.display_name)
                    if target and (target==name or name.endswith(' '+target)):
                        category='AIRLINE';provenance={'origin':'OFFICIAL_TARGET_PROGRAM_STATEMENT','document_version_id':str(document.id),'url':document.canonical_url,'excerpt':match[0]};break
                if category:break
        if not category:continue
        if program.category not in {'OTHER',category} or (alliance and program.alliance not in {None,alliance.value}):
            conflicts.append(str(program.id));continue
        changed=program.category!=category or (alliance and program.alliance!=alliance.value)
        if changed:
            program.category=category
            metadata={**program.metadata_provenance,'category':provenance}
            if alliance:program.alliance=alliance.value;metadata['alliance']=provenance
            program.metadata_provenance=metadata;updated.append({'program_ref':str(program.id),'name':program.display_name,'category':category,'alliance':program.alliance,'provenance':provenance})
    session.flush()
    return {'updated':updated,'conflicts':conflicts,'alliance_directory_as_of':ALLIANCE_DIRECTORY_AS_OF}
