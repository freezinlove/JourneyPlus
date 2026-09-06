"""Explicit old-ID resolution; never infer an activity from a brand name."""
from sqlalchemy import select
from journeyplus.models import StatusEvent,FactSetRecord,ArticleOpportunityRecord,ArticleAnalysisRecord,SourceItem
from journeyplus.knowledge.models import Activity,KnowledgeMigrationLink
from journeyplus.knowledge.ingestion_scope import article_scope_reason


def legacy_opportunity(session,identity):
    candidates=[]
    for model,table in ((StatusEvent,'status_events'),(FactSetRecord,'fact_sets'),(ArticleOpportunityRecord,'article_opportunities')):
        row=session.get(model,identity)
        if row is not None:candidates.append((table,row))
    if not candidates:return {'status':'NOT_FOUND','message':'历史活动不存在。'}
    if len(candidates)!=1:return {'status':'AMBIGUOUS','message':'历史标识对应多个来源，不能自动跳转。'}
    table,row=candidates[0]
    result={'legacy_table':table,'legacy_id':str(identity)}
    if table=='fact_sets':
        # Official cards/tree links use fact-set IDs, not event IDs. Follow the
        # explicit FK even for a historical version; never resolve by its title.
        identity=row.event_id
        row=session.get(StatusEvent,identity)
        if row is None:return {**result,'status':'UNRESOLVED','message':'历史事实所属活动不存在，需要复核。'}
        result['legacy_event_id']=str(identity)
        table='status_events'
    if table=='article_opportunities':
        analysis=session.get(ArticleAnalysisRecord,row.analysis_id)
        item=session.get(SourceItem,analysis.source_item_id) if analysis else None
        if item and article_scope_reason(item):
            return {**result,'status':'ARCHIVE_ONLY','message':'这篇旧文章不进入新的活动库；历史快照保留，不能作为当前匹配结果。'}
    links=list(session.scalars(select(KnowledgeMigrationLink).where(KnowledgeMigrationLink.legacy_table==table,
        KnowledgeMigrationLink.legacy_id==str(identity),KnowledgeMigrationLink.legacy_path=='',
        KnowledgeMigrationLink.target_table=='activities',KnowledgeMigrationLink.status=='MAPPED')))
    targets={link.target_id for link in links if link.target_id}
    if len(targets)!=1:return {**result,'status':'UNRESOLVED','message':'历史活动尚未完成明确关联；没有按项目名称猜测替代活动。'}
    activity=session.get(Activity,next(iter(targets)));seen=set()
    while activity and activity.merged_into_id:
        if activity.id in seen:return {**result,'status':'UNRESOLVED','message':'活动关联需要复核。'}
        seen.add(activity.id);activity=session.get(Activity,activity.merged_into_id)
    if activity is None:return {**result,'status':'UNRESOLVED','message':'活动关联目标不存在，需要复核。'}
    if not activity.current_version_id:return {**result,'status':'NOT_PUBLISHED','message':'已定位活动，但新资料尚未发布，暂不能作为匹配依据。'}
    return {**result,'status':'RESOLVED','activity_ref':str(activity.id),'version_ref':str(activity.current_version_id),
            'message':'已按历史标识定位到当前已发布资料；当前版本可能与旧简报不同。'}
