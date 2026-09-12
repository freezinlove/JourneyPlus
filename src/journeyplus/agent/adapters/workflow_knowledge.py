"""Read projections of the chosen AIWorkflow schema. No writes or shadow tables."""
from datetime import UTC, datetime
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
from journeyplus.agent.services.identities import canonical


def identity_id(kind, key):
    return uuid5(NAMESPACE_URL, 'journeyplus:workflow:' + kind + ':' + key)


def graph_state(session):
    # Cache only inside this read transaction; never hide later workflow updates.
    cached = session.info.get('workflow_graph')
    if cached is None or cached[0] is not session.get_transaction():
        state = UnifiedMembershipTreeService(session)._build_state(now=datetime.now(UTC))
        session.info['workflow_graph'] = (session.get_transaction(), state)
    return session.info['workflow_graph'][1]


def catalog(session):
    state = graph_state(session)
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


class WorkflowUserData:
    """Only route-source reads; current holdings schema has no unified tier FK."""
    def __init__(self, factory):
        self.factory = factory

    def route_sources(self, mode, refs=()):
        if mode != 'saved' and not refs:
            return []
        with self.factory() as session:
            statement = select(StatusHolding.id, StatusHolding.program_key, StatusHolding.tier_key,
                StatusHolding.program_display_name, StatusHolding.tier_display_name, StatusHolding.valid_until, StatusHolding.updated_at)
            if mode == 'saved':
                statement = statement.where((StatusHolding.valid_until.is_(None)) |
                    (StatusHolding.valid_until>=datetime.now(UTC).date()))
            if refs:
                statement = statement.where(StatusHolding.id.in_([UUID(r.removeprefix('holding:')) for r in refs]))
            rows = session.execute(statement.order_by(StatusHolding.id)).mappings().all()
            from .workflow_holdings import holding_revision
            result = [{'holding_ref':'holding:'+str(r['id']), 'revision':holding_revision(SimpleNamespace(**r)),
                'tier_ref':'tier:'+str(identity_id('tier',r['program_key']+'::'+r['tier_key'])),
                'program_name':r['program_display_name'], 'tier_name':r['tier_display_name'],
                'valid_until':r['valid_until'].isoformat() if r['valid_until'] else None} for r in rows]
            found = {r['holding_ref'] for r in result}
            result.extend({'holding_ref':r,'resolution_state':'INVALID_REFERENCE','code':'STALE_REFERENCE'}
                          for r in refs if r not in found)
            return result


class WorkflowKnowledgePort(KnowledgePort):
    catalog = staticmethod(catalog)
    user_data = WorkflowUserData

    @property
    def memory_type(self):
        from journeyplus.agent.services.workflow_memory import WorkflowUserMemory
        return WorkflowUserMemory

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
        for model, end in ((StatusEvent,StatusEvent.application_deadline_at),
                           (ArticleOpportunityRecord,ArticleOpportunityRecord.visibility_until_at)):
            for identity, start, finish in session.execute(select(model.id,model.application_start_at,end).order_by(model.id)):
                def state(value):
                    if value is None: return None
                    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
                    return aware<=now
                windows.append((str(identity),state(start),state(finish)))
        return ['workflow-v1',now.date().isoformat(),windows,*values]

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
        rows = [*events,*articles]
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
        # The original mappings are activity-wide, not duplicated per region.
        options.append({'ref':'mappings','label':'会籍匹配关系','availability':'UNKNOWN','mappings':mappings})
        brief_content = brief.content if brief else detail.brief.model_dump(mode='json') if detail.brief and not event else None
        source_ids = set()
        def evidence(value):
            if isinstance(value,dict):
                if value.get('document_version_id'): source_ids.add(UUID(value['document_version_id']))
                for child in value.values(): evidence(child)
            elif isinstance(value,list):
                for child in value: evidence(child)
        evidence(detail.facts.model_dump(mode='json'))
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
            'briefs':[{'content':brief_content}] if brief_content else [],
            'card':{'summary':brief_content.get('summary',detail.summary) if brief_content else detail.summary,
                    'lifecycle_status':detail.lifecycle_status,'source_links':detail.source_links},
            'brief_url':f'/opportunities/{record.id}'}

    def history(self, identity, *, before_version=None, limit=10):
        event = self.session.get(StatusEvent,identity)
        if not event:
            return {'activity_ref':str(identity),'versions':[],'has_more':False}
        statement=select(FactSetRecord).where(FactSetRecord.event_id==identity)
        if before_version is not None:statement=statement.where(FactSetRecord.version<before_version)
        rows=list(self.session.scalars(statement.order_by(FactSetRecord.version.desc()).limit(limit+1)))
        return {'activity_ref':str(identity),'versions':[{'version_ref':str(r.id),'version_no':r.version,
            'is_current':r.id==event.current_fact_set_id,'created_at':r.created_at.isoformat()} for r in rows[:limit]],
            'has_more':len(rows)>limit}

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
