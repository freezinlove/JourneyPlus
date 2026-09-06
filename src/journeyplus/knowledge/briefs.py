"""Version-bound deterministic brief projections; values remain in knowledge facts."""
from uuid import UUID
from sqlalchemy import select
from journeyplus.knowledge.models import ActivityBrief,ActivityKnowledgeVersion
from journeyplus.knowledge.reads import ActivityReadService


def generate_pending_briefs(factory, version_id: UUID) -> dict:
    with factory.begin() as s:
        version=s.get(ActivityKnowledgeVersion,version_id)
        if version is None or version.status!='PUBLISHED':raise ValueError('只能生成已发布版本的简报')
        reader=ActivityReadService(s);detail=reader.detail(version.activity_id,version.id)
        previous=reader.detail(version.activity_id,version.base_version_id) if version.base_version_id else None
        generated=0
        for brief in s.scalars(select(ActivityBrief).where(ActivityBrief.knowledge_version_id==version_id)):
            if brief.status=='READY' and brief.generator_version=='knowledge-3':continue
            content={'title':detail['name'],'version_ref':str(version_id),'summary':detail['facts']['summary'],
                     'option_refs':[o['ref'] for o in detail['options']], 'fact_paths':['facts.lifecycle','facts.application_window','facts.conditions','facts.caveats']}
            if brief.brief_kind=='UPDATE':
                from journeyplus.knowledge.brief_changes import changes_between
                content['changes']=changes_between(previous,detail)
            brief.generator_version='knowledge-3';brief.content=content;brief.fact_refs=content['fact_paths'];brief.status='READY';brief.error_code=None;generated+=1
        return {'generated':generated,'version_id':str(version_id)}
