"""Incremental bridge from collected official/ordinary sources to one knowledge store.

This consumes existing permitted DocumentVersions. It never crawls StatusMatcher or
silently switches a legacy product consumer.
"""
from __future__ import annotations

from uuid import UUID
from datetime import UTC, datetime, timedelta
from sqlalchemy import select

from journeyplus.models import (StatusMatchWatch, StatusMatchWatchPage, StatusEvent, FactSetRecord,
    ArticleOpportunityRecord, ArticleAnalysisRecord, DocumentVersion, SourceItem, now_utc)
from journeyplus.knowledge.contracts import DocumentBinding, KnowledgeDraft
from journeyplus.knowledge.models import Activity, ActivityDocument, ActivityObservationState, ActivityBrief, ActivityKnowledgeVersion
from journeyplus.knowledge.publication import CatalogService, PublicationService, signature
from journeyplus.knowledge.workflow import KnowledgeWorkflow
from journeyplus.knowledge.sources import section_document, create_evidence
from journeyplus.knowledge.migration import _link


from journeyplus.knowledge.ingestion_scope import article_scope_reason


class KnowledgeRefreshService:
    def __init__(self, factory, provider):
        self.factory = factory
        self.workflow = KnowledgeWorkflow(factory, provider)

    def _identity(self, s, old, table, facts):
        catalog = CatalogService(s)
        program = catalog.program(old.program)
        # Old mappings bootstrap names only; they do not become new mapping facts.
        for mapping in facts.get('status_mappings') or []:
            if mapping.get('target_tier'):catalog.tier(program.id,mapping['target_tier'])
            if mapping['source_program'].casefold().startswith(('all major ', 'all eligible ')):
                continue
            source = catalog.program(mapping['source_program'])
            for name in mapping.get('source_tiers') or []:
                catalog.tier(source.id, name)
            if mapping.get('target_tier'):
                catalog.tier(program.id, mapping['target_tier'])
        for route in facts.get('application_routes') or []:
            for price in route.get('prices') or []:
                tier = price.get('target_tier') or price.get('target_status')
                if isinstance(tier, str) and tier.strip():catalog.tier(program.id, tier)
        key = f'legacy:{table}:{old.id}'
        activity = s.scalar(select(Activity).where(Activity.identity_key == key))
        if activity is None and table=='article_opportunities':
            analysis=s.get(ArticleAnalysisRecord,old.analysis_id)
            prior=list(s.scalars(select(Activity).join(ActivityDocument,ActivityDocument.knowledge_version_id==Activity.current_version_id)
                .join(DocumentVersion,DocumentVersion.id==ActivityDocument.document_version_id)
                .join(ArticleAnalysisRecord,ArticleAnalysisRecord.document_version_id==DocumentVersion.id)
                .where(ArticleAnalysisRecord.source_item_id==analysis.source_item_id,Activity.primary_program_id==program.id,Activity.merged_into_id.is_(None)).distinct()))
            if len(prior)==1:activity=prior[0]
            elif len(prior)>1:raise ValueError('同一文章项目存在多条活动关联，需要核对期次')
        if activity is None:
            activity = Activity(identity_key=key, primary_program_id=program.id,
                kind=facts.get('opportunity_kind', 'OTHER'), edition_key=f'legacy:{old.id}')
            s.add(activity);s.flush()
        _link(s, table, old.id, '', 'activities', activity.id, 'MAPPED', 'Explicit collected source identity')
        return activity

    def official(self, host: str, *, force=False):
        with self.factory.begin() as s:
            watch = s.scalar(select(StatusMatchWatch).where(StatusMatchWatch.host == host))
            if watch is None or not watch.current_event_id:raise ValueError('官方来源尚未确定活动身份')
            event = s.get(StatusEvent, watch.current_event_id)
            record = s.get(FactSetRecord, event.current_fact_set_id) if event.current_fact_set_id else None
            activity = self._identity(s, event, 'status_events', record.facts if record else {})
            aid = activity.id
            pages = {p.page_kind:p for p in s.scalars(select(StatusMatchWatchPage).where(StatusMatchWatchPage.watch_id == watch.id))}
            error = watch.last_error or next((pages[k].last_error for k in pages if pages[k].last_error), None)
            complete = all(k in pages and pages[k].current_document_version_id for k in ('activity','faq','terms'))
            if error or not complete:
                self._observe(s, aid, error='INCOMPLETE_OFFICIAL_SNAPSHOT')
                return {'activity_id':str(aid), 'status':'DEFERRED', 'reason':'官方三页不完整或本次检查失败，保留已发布版本'}
            bindings=[]
            for kind in ('activity','faq','terms'):
                doc=s.get(DocumentVersion,pages[kind].current_document_version_id)
                # Exclude explicitly historical sections without changing immutable text.
                sections=section_document(s,doc.id)
                end=len(doc.normalized_body)
                import re
                match=re.search(r'(?im)^.*Recently ended offers.*$',doc.normalized_body)
                if match:end=match.start()
                scope=[x.id for x in sections if x.locator.get('end',end+1)<=end]
                if not scope:
                    self._observe(s,aid,error='NO_CURRENT_OFFICIAL_CONTENT')
                    return {'activity_id':str(aid),'status':'DEFERRED','reason':'官方页面没有可发布的当前正文','model_calls':0}
                bindings.append(DocumentBinding(document_version_id=doc.id,
                    role='OFFICIAL_PRIMARY' if kind=='activity' else 'OFFICIAL_SUPPORT',section_ids=scope))
        return self._process(aid,bindings,force=force)

    def closed_event(self, event_id: UUID):
        """Replay a verified HOME closure even after the legacy watch was removed."""
        from types import SimpleNamespace
        from journeyplus.statusmatch.closure import assess_statusmatch_home_closure
        with self.factory.begin() as s:
            event=s.get(StatusEvent,event_id)
            if event is None or event.closure_document_version_id is None:
                raise ValueError('关闭事件缺少 HOME 证据')
            doc=s.get(DocumentVersion,event.closure_document_version_id)
            item=s.get(SourceItem,doc.source_item_id)
            assessment=assess_statusmatch_home_closure(activity=doc,activity_item=item)
            if not assessment.closed:
                return {'status':'DEFERRED','reason':'HOME_CLOSURE_NOT_CONFIRMED','model_calls':0}
            sections=section_document(s,doc.id)
            evidence_section=next((section for section in sections if assess_statusmatch_home_closure(
                activity=SimpleNamespace(raw_body=None,normalized_body=section.body,canonical_url=doc.canonical_url),
                activity_item=item).closed),None)
            if evidence_section is None:
                return {'status':'DEFERRED','reason':'HOME_CLOSURE_EVIDENCE_NOT_LOCATABLE','model_calls':0}
            record=s.get(FactSetRecord,event.current_fact_set_id) if event.current_fact_set_id else None
            activity=self._identity(s,event,'status_events',record.facts if record else {'opportunity_kind':'STATUS_MATCH'})
            aid=activity.id
            previous=s.get(ActivityKnowledgeVersion,activity.current_version_id) if activity.current_version_id else None
            evidence=create_evidence(s,evidence_section.id,evidence_section.body)
            draft=KnowledgeDraft.model_validate({
                'activity_id':aid,'base_version_id':activity.current_version_id,
                'extraction_key':'home-closure:'+signature({'activity':str(aid),'document':str(doc.id)}),
                'documents':[{'document_version_id':doc.id,'role':'OFFICIAL_PRIMARY','section_ids':[evidence_section.id]}],
                'facts':{'title':previous.facts['title'] if previous else event.program+' 会籍匹配',
                         'summary':{'value':'官方活动首页已确认关闭申请。','known_state':'KNOWN','evidence_ids':[evidence.id]},
                         'lifecycle':{'value':'CLOSED','known_state':'KNOWN','evidence_ids':[evidence.id]}},
                'options':[]})
            version=PublicationService(s).publish(draft)
            vid=version.id
            self._observe(s,aid,source_time=doc.fetched_at)
        return {'status':'REUSED' if previous and previous.id==vid else 'PUBLISHED',
                'activity_id':str(aid),'version_id':str(vid),'model_calls':0,'briefs':self._briefs(vid)}

    def article(self, opportunity_id: UUID, *, force=False):
        with self.factory.begin() as s:
            old=s.get(ArticleOpportunityRecord,opportunity_id)
            if old is None:raise ValueError('文章活动不存在')
            analysis=s.get(ArticleAnalysisRecord,old.analysis_id)
            item=s.get(SourceItem,analysis.source_item_id)
            reason=article_scope_reason(item)
            if reason:
                return {'status':'DEFERRED','reason':reason,'source_ref':str(item.id),'model_calls':0}
            peers=list(s.scalars(select(ArticleOpportunityRecord).where(ArticleOpportunityRecord.analysis_id==old.analysis_id)))
            activity=self._identity(s,old,'article_opportunities',old.facts)
            aid=activity.id
            # A multi-activity article needs explicit scoped evidence before publication.
            # Never use the whole article as if all of its prices belong to each activity.
            if len(peers)>1:
                self._observe(s,aid,error='ARTICLE_SECTION_SCOPE_REQUIRED')
                return {'activity_id':str(aid),'status':'DEFERRED','reason':'一文多活动需要先核对分段关联'}
            binding=DocumentBinding(document_version_id=analysis.document_version_id,role='THIRD_PARTY')
        return self._process(aid,[binding],force=force)

    def _observe(self,s,aid,*,error=None,source_time=None,oldest_source_time=None):
        observation=s.get(ActivityObservationState,aid)
        if observation is None:
            observation=ActivityObservationState(activity_id=aid);s.add(observation)
        observation.last_checked_at=now_utc();observation.last_error=error
        if error:observation.freshness='INCOMPLETE'
        elif source_time:
            if source_time.tzinfo is None:source_time=source_time.replace(tzinfo=UTC)
            observation.last_source_changed_at=source_time
            freshness_time=oldest_source_time or source_time
            if freshness_time.tzinfo is None:freshness_time=freshness_time.replace(tzinfo=UTC)
            observation.freshness='STALE' if freshness_time<now_utc()-timedelta(days=30) else 'FRESH'

    def _process(self,aid,bindings,*,force):
        with self.factory() as s:
            activity=s.get(Activity,aid)
            current=list(s.scalars(select(ActivityDocument).where(ActivityDocument.knowledge_version_id==activity.current_version_id))) if activity.current_version_id else []
            expected={(str(b.document_version_id),b.role,tuple(sorted(map(str,b.section_ids)))) for b in bindings}
            actual={(str(b.document_version_id),b.role,tuple(sorted(b.section_scope))) for b in current}
            source_times=[s.get(DocumentVersion,b.document_version_id).fetched_at for b in bindings]
            source_time=max(source_times);oldest_source_time=min(source_times)
            version_id=activity.current_version_id
        if actual==expected and not force:
            with self.factory.begin() as s:self._observe(s,aid,source_time=source_time,oldest_source_time=oldest_source_time)
            return {'activity_id':str(aid),'version_id':str(version_id),'status':'REUSED','model_calls':0,'briefs':self._briefs(version_id)}
        try:
            result=self.workflow.process(aid,bindings)
            with self.factory.begin() as s:self._observe(s,aid,source_time=source_time,oldest_source_time=oldest_source_time)
            result['briefs']=self._briefs(UUID(result['version_id']))
            return result
        except Exception as exc:
            with self.factory.begin() as s:self._observe(s,aid,error=type(exc).__name__)
            raise

    def _briefs(self,version_id):
        from journeyplus.knowledge.briefs import generate_pending_briefs
        try:return generate_pending_briefs(self.factory,version_id)
        except Exception as exc:
            with self.factory.begin() as s:
                for brief in s.scalars(select(ActivityBrief).where(ActivityBrief.knowledge_version_id==version_id,ActivityBrief.status!='READY')):
                    brief.status='FAILED';brief.error_code=type(exc).__name__
            return {'status':'FAILED','error_code':type(exc).__name__}

    def pending(self, *, limit=10):
        if not 1<=limit<=100:raise ValueError('limit must be between 1 and 100')
        with self.factory() as s:
            closures=list(s.scalars(select(StatusEvent.id).where(StatusEvent.closure_document_version_id.is_not(None)).order_by(StatusEvent.archived_at.desc()).limit(100)))
            hosts=list(s.scalars(select(StatusMatchWatch.host).where(StatusMatchWatch.current_event_id.is_not(None)).order_by(StatusMatchWatch.last_changed_at.desc()).limit(100)))
            articles=list(s.scalars(select(ArticleOpportunityRecord.id).order_by(ArticleOpportunityRecord.updated_at.desc()).limit(100)))
        results=[];attempted=0
        for kind,key in [('closed_event',e) for e in closures]+[('official',h) for h in hosts]+[('article',a) for a in articles]:
            if attempted>=limit:break
            try:
                result=getattr(self,kind)(key);results.append(result)
                if result['status'] not in {'REUSED','DEFERRED'}:attempted+=1
            except Exception as exc:
                attempted+=1
                results.append({'source_kind':kind,'source_ref':str(key),'status':'FAILED','error_code':type(exc).__name__})
        return results
