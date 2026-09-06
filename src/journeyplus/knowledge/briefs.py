"""Version-bound deterministic brief projections; values remain in knowledge facts."""
from uuid import UUID
from sqlalchemy import select
from journeyplus.knowledge.models import ActivityBrief,ActivityKnowledgeVersion,ApplicationOptionVersion
from journeyplus.knowledge.reads import ActivityReadService
from journeyplus.knowledge.publication import _semantic


def generate_pending_briefs(factory, version_id: UUID) -> dict:
    with factory.begin() as s:
        version=s.get(ActivityKnowledgeVersion,version_id)
        if version is None or version.status!='PUBLISHED':raise ValueError('只能生成已发布版本的简报')
        reader=ActivityReadService(s);detail=reader.detail(version.activity_id,version.id)
        previous=reader.detail(version.activity_id,version.base_version_id) if version.base_version_id else None
        generated=0
        for brief in s.scalars(select(ActivityBrief).where(ActivityBrief.knowledge_version_id==version_id)):
            if brief.status=='READY':continue
            content={'title':detail['name'],'version_ref':str(version_id),'summary':detail['facts']['summary'],
                     'option_refs':[o['ref'] for o in detail['options']], 'fact_paths':['facts.lifecycle','facts.application_window','facts.conditions','facts.caveats']}
            if brief.brief_kind=='UPDATE':
                changes=[]
                for field in ('summary','conditions','lifecycle','application_window','caveats'):
                    if _semantic(previous['facts'].get(field))!=_semantic(detail['facts'].get(field)):
                        changes.append({'scope':'ACTIVITY','path':f'facts.{field}','before_version_ref':str(version.base_version_id),'after_version_ref':str(version_id)})
                before={o['logical_ref']:o for o in previous['options']};after={o['logical_ref']:o for o in detail['options']}
                for identity in before.keys()|after.keys():
                    old=before.get(identity);new=after.get(identity)
                    if old is None or new is None:
                        changes.append({'scope':'OPTION','logical_ref':identity,'change':'ADDED' if old is None else 'REMOVED'});continue
                    for field in ('prices','mappings','conditions','challenge','application_window','status_validity','availability'):
                        def stable(v):
                            if isinstance(v,dict):return {k:stable(x) for k,x in _semantic(v).items() if k not in {'ref','evidence_ids'}}
                            if isinstance(v,list):return [stable(x) for x in v]
                            return v
                        if stable(old[field])!=stable(new[field]):changes.append({'scope':'OPTION','logical_ref':identity,'path':field,'before_ref':old['ref'],'after_ref':new['ref']})
                content['changes']=changes
            brief.content=content;brief.fact_refs=content['fact_paths'];brief.status='READY';brief.error_code=None;generated+=1
        return {'generated':generated,'version_id':str(version_id)}
