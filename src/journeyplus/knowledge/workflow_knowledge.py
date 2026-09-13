"""Read projections of the chosen AIWorkflow schema. No writes or shadow tables."""
from datetime import UTC, datetime
from journeyplus.lifecycle.visibility import is_ended
from types import SimpleNamespace
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import load_only

from journeyplus.knowledge.access import KnowledgePort
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.models import (StatusEvent, FactSetRecord, BriefRecord, ArticleOpportunityRecord,
    ArticleAnalysisRecord, ArticleBriefRecord, StatusMatchArticleSupplement, StatusMatchWatch, StatusMatchArticleRoute,
    SourceItem, DocumentVersion, StatusHolding)
from journeyplus.product.opportunities import PersonalizedMatchService
from .text import canonical


def identity_id(kind, key):
    return uuid5(NAMESPACE_URL, 'journeyplus:workflow:' + kind + ':' + key)


def brief_url(activity, version):
    return f'/knowledge?activity_id={activity}&version_ref={version}&section=brief'


def graph_state(session):
    # Cache only inside this read transaction; never hide later workflow updates.
    cached = session.info.get('workflow_graph')
    if cached is None or cached[0] is not session.get_transaction():
        state = UnifiedMembershipTreeService(session)._build_state(now=datetime.now(UTC))
        session.info['workflow_graph'] = (session.get_transaction(), state)
    return session.info['workflow_graph'][1]


def catalog(session, *, state=None):
    state = state if state is not None else graph_state(session)
    programs, tiers, aliases = {}, [], []
    for node in sorted(state.nodes.values(), key=lambda n: n.id):
        pid = identity_id('program', node.program_key)
        categories = {str(c) for c in node.categories} - {'UNKNOWN'}
        programs.setdefault(pid, SimpleNamespace(id=pid, display_name=node.program,
            canonical_key=node.program_key, category=next(iter(categories)) if len(categories)==1 else 'OTHER',
            alliance=str(node.alliance) if node.alliance else None))
        tiers.append(SimpleNamespace(id=identity_id('tier',node.id), program_id=pid,
            display_name=node.tier, canonical_key=node.tier_key))
    for key, record in state.registry.programs.items():
        pid = identity_id('program', key)
        if pid in programs:
            aliases.extend(SimpleNamespace(program_id=pid,tier_id=None,normalized_alias=name,
                locale=None,origin='WORKFLOW_CATALOG') for name in sorted(record.aliases))
    return sorted(programs.values(),key=lambda p:p.display_name), tiers, aliases


class WorkflowKnowledgePort(KnowledgePort):
    catalog = staticmethod(catalog)

    @staticmethod
    def activity_reader(session):
        return WorkflowActivityReader(session)

    @staticmethod
    def route_service(session, *, holding_snapshot=None):
        from .workflow_routes import WorkflowRouteService
        return WorkflowRouteService(session, holding_snapshot=holding_snapshot)

    @staticmethod
    def current_version(session, identity):
        event = session.get(StatusEvent, identity)
        if event:
            return str(event.current_fact_set_id) if event.current_fact_set_id else None
        article = session.get(ArticleOpportunityRecord, identity)
        return str(article.analysis_id) if article else None

    def availability(self):
        with self.read() as session:
            programs, tiers, _ = catalog(session)
            count = len(WorkflowActivityReader(session).locate(limit=100000))
        return {'status':'AVAILABLE' if count else 'UNAVAILABLE', 'program_count':len(programs),
                'tier_count':len(tiers), 'activity_count':count,
                'message':None if count else '当前 AIWorkflow 尚无可读取的活动数据。'}

    @staticmethod
    def snapshot_values(session, name):
        models = (StatusEvent, FactSetRecord, BriefRecord, ArticleOpportunityRecord,
                  ArticleAnalysisRecord, ArticleBriefRecord, StatusMatchArticleSupplement, StatusMatchWatch, StatusMatchArticleRoute, SourceItem, DocumentVersion)
        values = [[tuple(r) for r in session.execute(select(m.id,m.updated_at).order_by(m.id))] for m in models]
        now = datetime.now(UTC)
        windows = []
        from journeyplus.lifecycle.visibility import effective_status, contributes
        for model in (StatusEvent, ArticleOpportunityRecord):
            fields = [model.id, model.archived_at, model.lifecycle_status,
                      model.application_start_at, model.application_deadline_at]
            fields += ([model.visibility_until_at, model.visibility_policy, model.archive_reason]
                       if model is ArticleOpportunityRecord else [model.merged_into_id])
            for row in session.scalars(select(model).options(load_only(*fields)).order_by(model.id)):
                windows.append((str(row.id), effective_status(row, now=now), contributes(row, now=now)))
        return ['workflow-v2-lifecycle',now.date().isoformat(),windows,*values]

    @staticmethod
    def holding_snapshot(session):
        return [tuple(r) for r in session.execute(select(StatusHolding.id,StatusHolding.updated_at,
            StatusHolding.program_key,StatusHolding.tier_key,StatusHolding.valid_until).order_by(StatusHolding.id))]

    def read_reference(self, ref):
        kind, _, raw = ref.partition(':')
        with self.read() as session:
            if kind == 'activity':
                identity, sep, version = raw.partition('@')
                if not sep:
                    raise ValueError('Activity reference requires a FactSet/analysis version')
                return self.activity_reader(session).detail(UUID(identity),UUID(version))
            programs, tiers, _ = catalog(session)
            rows = programs if kind=='program' else tiers if kind=='tier' else []
            row = next((row for row in rows if str(row.id)==raw),None)
            if row is None:
                raise LookupError('Workflow identity not found')
            return {'ref':ref,'name':row.display_name}


class WorkflowActivityReader:
    def __init__(self, session):
        self.session = session

    def locate(self, *, ref=None, text=None, limit=5, offset=0):
        events = list(self.session.scalars(select(StatusEvent).where(StatusEvent.merged_into_id.is_(None),
            StatusEvent.current_fact_set_id.is_not(None)).order_by(StatusEvent.id)))
        # Only the most recent successful analysis of each article is current.
        analyses = list(self.session.scalars(select(ArticleAnalysisRecord).where(
            ArticleAnalysisRecord.status=='SUCCEEDED').order_by(ArticleAnalysisRecord.created_at.desc(),ArticleAnalysisRecord.id.desc())))
        latest = {}
        for a in analyses:
            latest.setdefault(a.source_item_id,a.id)
        articles = list(self.session.scalars(select(ArticleOpportunityRecord).where(
            ArticleOpportunityRecord.analysis_id.in_(latest.values())).order_by(ArticleOpportunityRecord.id)))
        rows = [r for r in [*events,*articles] if not is_ended(r)]
        if ref:
            direct = [r for r in rows if str(r.id)==ref]
            if direct:
                return direct
            programs, tiers, _ = catalog(self.session)
            program = next((p for p in programs if str(p.id)==ref),None)
            tier = next((t for t in tiers if str(t.id)==ref),None)
            if tier:
                program = next(p for p in programs if p.id==tier.program_id)
            if not program:
                return []
            text = program.display_name
        if text:
            tokens = canonical(text).split()
            rows = [r for r in rows if all(t in canonical(' '.join(filter(None,
                [r.program,r.summary,r.target_status,getattr(r,'search_text','')]))) for t in tokens)]
        return rows[offset:offset+limit+1]

    def detail(self, identity, version=None):
        event = self.session.get(StatusEvent, identity)
        if event:
            selected = version or event.current_fact_set_id
            record = self.session.get(FactSetRecord, selected) if selected else None
            if record is None or record.event_id != identity:
                raise ValueError('Activity FactSet version does not belong to this event')
            detail = PersonalizedMatchService(self.session).detail(record.id,include_current_path=False)
            # Historical facts must never acquire the current version's brief.
            brief = self.session.get(BriefRecord,event.current_brief_id) if event.current_brief_id else None
            if brief is None or brief.fact_set_id!=record.id:
                brief = self.session.scalar(select(BriefRecord).where(BriefRecord.fact_set_id==record.id)
                    .order_by(BriefRecord.version.desc()).limit(1))
            current = str(event.current_fact_set_id)
        else:
            record = self.session.get(ArticleOpportunityRecord,identity)
            if record is None:
                raise LookupError('Workflow activity not found')
            if version and version != record.analysis_id:
                raise ValueError('Article analysis version mismatch')
            selected = record.analysis_id
            detail = PersonalizedMatchService(self.session).detail(record.id,include_current_path=False)
            brief = None
            analysis = self.session.get(ArticleAnalysisRecord,record.analysis_id)
            latest = self.session.scalar(select(ArticleAnalysisRecord.id).where(
                ArticleAnalysisRecord.source_item_id==analysis.source_item_id,
                ArticleAnalysisRecord.status=='SUCCEEDED').order_by(
                ArticleAnalysisRecord.created_at.desc(),ArticleAnalysisRecord.id.desc()).limit(1))
            current = str(selected) if latest==record.analysis_id else None
        facts = detail.facts.model_dump(mode='json')
        mappings = [{'ref':'mapping-'+str(i), 'from_program':m['source_program'],
            'from_tiers':m['source_tiers'], 'to_program':detail.program, 'to_tier':m['target_tier'], **m}
            for i,m in enumerate(facts.pop('status_mappings',[]))]
        routes = facts.pop('application_routes',[])
        options = [{'ref':'route-'+str(i), 'label':r['scope'], 'availability':'CONFLICT' if r['conflict'] else 'UNKNOWN',
                    **r, 'mappings':[]} for i,r in enumerate(routes)]
        from journeyplus.product.brief_data import fee_view
        for option, route in zip(options, detail.facts.application_routes):
            option['fee'] = fee_view(detail.facts.model_copy(update={'application_routes':[route]})).model_dump(mode='json')
        # The original mappings are activity-wide, not duplicated per region.
        options.append({'ref':'mappings','label':'会籍匹配关系','availability':'UNKNOWN','mappings':mappings})
        brief_content = brief.content if brief else detail.brief.model_dump(mode='json') if detail.brief and not event else None
        from .source_documents import source_documents
        source_ids = {document.id for document in source_documents(self.session, record)}
        if event and brief:
            from journeyplus.statusmatch.composed_brief import _latest_routes_for_event, _current_supplements
            supplements = _current_supplements(self.session,
                routes=_latest_routes_for_event(self.session,event.id),fact_set_id=record.id,brief_id=brief.id)
            facts['article_supplements'] = [{'highlights':s.highlights,
                'source_document_ref':str(s.article_document_version_id)} for s in supplements]
            source_ids.update(s.article_document_version_id for s in supplements)

        sources = [dict(document_version_ref=str(d.id),url=d.canonical_url,fetched_at=d.fetched_at.isoformat())
            for d in self.session.scalars(select(DocumentVersion).options(load_only(DocumentVersion.id,
                DocumentVersion.canonical_url,DocumentVersion.fetched_at)).where(DocumentVersion.id.in_(source_ids)))]
        return {'data_model':'aiworkflow','ref':str(identity),'version_ref':str(selected),'current_version_ref':current,
            'is_current':str(selected)==current,'name':brief_content.get('title',detail.program) if brief_content else detail.program,
            'kind':str(detail.opportunity_kind),'facts':facts,'options':options,'sources':sources,
            'fee':fee_view(detail.facts).model_dump(mode='json'),
            'briefs':[{'content':brief_content}] if brief_content else [],
            'card':{'summary':brief_content.get('summary',detail.summary) if brief_content else detail.summary,
                    'lifecycle_status':detail.lifecycle_status,'source_links':detail.source_links},
            'brief_url':brief_url(identity,selected)}

    def history(self, identity, *, before_version=None, limit=10):
        event = self.session.get(StatusEvent,identity)
        if not event:
            return {'activity_ref':str(identity),'versions':[],'has_more':False,'next_before_version':None}
        statement=select(FactSetRecord).where(FactSetRecord.event_id==identity)
        if before_version is not None:statement=statement.where(FactSetRecord.version<before_version)
        rows=list(self.session.scalars(statement.order_by(FactSetRecord.version.desc()).limit(limit+1)))
        selected = rows[:limit]
        # History only needs presence/status, not every brief's complete content.
        ready = set(self.session.scalars(select(BriefRecord.fact_set_id).where(
            BriefRecord.fact_set_id.in_([r.id for r in selected]))))
        return {'activity_ref':str(identity),'versions':[{'version_ref':str(r.id),'version_no':r.version,
            'is_current':r.id==event.current_fact_set_id,'created_at':r.created_at.isoformat(),
            'brief_status':'READY' if r.id in ready else 'MISSING',
            'brief_url':brief_url(identity,r.id) if r.id in ready else None} for r in selected],
            'has_more':len(rows)>limit,
            'next_before_version':selected[-1].version if len(rows)>limit else None}

    def materials(self, *, selector, version_ref, section_refs=(), aspects=(), **unused):
        detail = self.detail(UUID(selector['ref']),UUID(version_ref))
        sources = {s['document_version_ref']:s for s in detail['sources']}
        snippets = []
        # Default evidence view is a source directory. Original text is fetched
        # only for explicitly requested document sections, never per-field checks.
        for ref in section_refs:
            raw = ref.removeprefix('document:')
            doc_id, _, chunk = raw.partition(':')
            if doc_id not in sources:
                raise ValueError('Source does not belong to this activity version')
            index = int(chunk or '0')
            if index < 0: raise ValueError('Invalid document chunk')
            body = self.session.scalar(select(DocumentVersion.normalized_body).where(DocumentVersion.id==UUID(doc_id))) or ''
            start = index*6000
            if start >= len(body): raise LookupError('Document chunk not found')
            snippets.append({'ref':ref,'url':sources[doc_id]['url'],'text':body[start:start+6000],
                'next_ref':f'document:{doc_id}:{index+1}' if start+6000<len(body) else None})
        fields = {'PRICE':('cost',), 'ELIGIBILITY':('eligibility','region'),
                  'CHALLENGE':('challenge_requirements',), 'WINDOW':('application_start','deadline'),
                  'VALIDITY':('status_validity',), 'APPLICATION':('action_link',)}
        requested = {field for aspect in aspects for field in fields.get(aspect,())}
        if aspects: requested.update(('eligibility','region','caveats'))
        facts = [{'field':field,'value':detail['facts'].get(field)} for field in sorted(requested)]
        for option in detail['options']:
            if option['ref']=='mappings': continue
            selected = {'PRICE':('prices','cost'), 'ELIGIBILITY':('eligibility','region'),
                        'APPLICATION':('action_link',)}
            for field in sorted({f for aspect in aspects for f in selected.get(aspect,())}):
                facts.append({'option_ref':option['ref'],'scope':option['label'],
                    'region':option.get('region'),'field':field,'value':option.get(field)})
        return {'data':{'facts':facts, 'catalog':[{**s,'section_ref':'document:'+key+':0'} for key,s in sources.items()],
                        'snippets':snippets},
                'coverage':{'complete':not any(s['next_ref'] for s in snippets),'scope':'requested_document_chunks'},
                'expansions':[], 'caveats':[]}
