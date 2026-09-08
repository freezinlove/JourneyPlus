"""Deterministic browsing of a previously executed query; never an Agent turn."""
from copy import deepcopy
from sqlalchemy import select
from journeyplus.agent.workspace_models import WorkspaceMessage
from journeyplus.agent.read_basis import read_basis
from journeyplus.knowledge.pagination import _cursor,continue_search
from journeyplus.knowledge.publication import signature
from journeyplus.knowledge.references import ReferenceMap
from journeyplus.knowledge.routes import RouteService
from journeyplus.models import now_utc


def browse_routes(service,workspace_id,request):
    from journeyplus.agent.workspace import WorkspaceError
    key=signature({'presentation':request.presentation_id,'anchor':request.anchor_ref,'cursor':request.cursor})[:32]
    with service.factory() as session:
        row=service._load(session,workspace_id)
        state=deepcopy(row.state)
        if key in state.get('browse_presentations',{}):return service._view(session,row)
        if row.active_turn_id or row.revision!=request.expected_revision:raise WorkspaceError('工作区已改变，请刷新后继续浏览')
        message=session.scalar(select(WorkspaceMessage).where(WorkspaceMessage.workspace_id==workspace_id,WorkspaceMessage.content['id'].as_string()==request.presentation_id))
        original=message.content if message else state.get('browse_presentations',{}).get(request.presentation_id)
        if original is None or not any(request.anchor_ref in block.get('subject_refs',[]) for block in original.get('blocks',[])):
            raise WorkspaceError('路线不属于所选展示')
        refs=ReferenceMap(state);anchor=refs.decode(request.anchor_ref)
        search_id=state.get('route_search_refs',{}).get(anchor)
        record=state.get('route_searches',{}).get(search_id)
        if record is None:raise WorkspaceError('原路径浏览快照已过期，请重新查询')
        route_service=RouteService(session)
        shown=set(refs.decode([ref for block in original.get('blocks',[]) for ref in block.get('subject_refs',[])]))
        offset=0
        # Skip only a prefix actually displayed. A recommended subset may be
        # non-contiguous; never skip undisclosed candidates between its items.
        while offset<len(record['route_refs']) and record['route_refs'][offset] in shown:offset+=1
        packet=continue_search(state,request.cursor or _cursor(state,search_id,offset),current_snapshot=route_service.current_snapshot(),query_hash=record['query_hash'],evaluation_context=route_service.evaluation_context())
        if packet['status']=='EXPIRED':raise WorkspaceError('资料、会籍或浏览快照已变化，请重新查询；原卡片保持不变')
    return _save_page(service,workspace_id,request.expected_revision,state,packet,key)


def explore_routes(service,workspace_id,request):
    from journeyplus.agent.workspace import WorkspaceError
    with service.factory() as session:
        row=service._load(session,workspace_id)
        if row.active_turn_id or row.revision!=request.expected_revision:raise WorkspaceError('工作区已改变，请刷新后重试')
        state=deepcopy(row.state)
    # Form selections are explicit user input, not an inferred chat follow-up.
    # Old conversational guards must not erase filters or reject a new source.
    state.update(public_task_active=False,unrestricted_route_active=False,source_change_requested=True)
    for field in ('turn_route_plan','planned_source_programs','planned_target_programs','planned_source_tier_groups','replaced_source_ids','source_identity_pending','target_change_requested','unresolved_question'):
        state.pop(field,None)
    query=request.query
    public=query.use_saved_holdings is False and not query.starting_tier_ids
    state['task_context']={'intent':'PUBLIC_OPPORTUNITIES' if public else 'ROUTES','hypothetical_empty':public,
                          'target_scope':'SELECTED' if query.target_program_id or query.target_tier_id else 'ANY',
                          'category_scope':'SELECTED' if query.category else 'ANY'}
    packet=service._tool('query_membership_routes',{'mode':'EXPLORE','query':request.query.model_dump(mode='json')},state,'按页面明确选择的条件探索')
    pending=state.get('pending_action')
    if pending and pending.get('kind')=='QUERY_ADJUST' and pending.get('query_hash')!=signature(state.get('query')):state.pop('pending_action',None)
    key=signature({'query':state.get('query'),'snapshot':packet.get('snapshot_ref'),'revision':request.expected_revision})[:32]
    return _save_page(service,workspace_id,request.expected_revision,state,packet,key)


def _save_page(service,workspace_id,revision,state,packet,key):
    from journeyplus.agent.workspace import WorkspaceError
    refs=ReferenceMap(state)
    # Assembly may read bound version details but has no provider/research calls.
    # This is a bounded page for the browser, not a model decision packet.
    # Applying the model token limit here could skip candidates as the cursor advances.
    refs.encode({'data':{'cards':packet['data']['cards'],'steps':packet['data']['steps']}})
    selected=[r['ref'] for r in packet['data']['cards']]
    saved={key:state.get(key) for key in ('comparison_scope','current_question','current_research_results','last_research_state','unrestricted_route_active')}
    state.update(comparison_scope=[],current_question='浏览原查询的匹配关系',current_research_results=[],last_research_state='NOT_REQUESTED',unrestricted_route_active=False)
    presentation=service._assemble({'text':'原查询的路径浏览','blocks':[{'type':'route_graph','graph_mode':'EXPLORE','subject_refs':refs.encode(selected),'fact_refs':[]}] if selected else [],'next_steps':[]},state,refs)
    for block in presentation['blocks']:
        for route in block['payload'].get('routes',[]):
            ref=refs.decode(route['ref']);record=state.get('route_searches',{}).get(state.get('route_search_refs',{}).get(ref),{})
            if ref in record.get('route_refs',[]):route['presentation_index']=record['route_refs'].index(ref)+1
    state.update(saved)
    presentation.update(id=key,role='BROWSE',text='原查询的路径浏览' if selected else presentation['text'],created_at=now_utc().isoformat(),next_steps=[],basis=[read_basis('query_membership_routes',packet,'BROWSE')],browse_cursor=packet.get('next_cursor'))
    presentation['query_summary']={field:packet['data'].get('query',{}).get(field) for field in ('category','alliance','max_amount','currency','free_only')}
    presentation.pop('route_exploration',None)
    browsed=state.setdefault('browse_presentations',{});browsed[key]=presentation
    if len(browsed)>24:
        oldest=min(browsed,key=lambda item:browsed[item]['created_at']);del browsed[oldest]
    allowed=[ref for block in presentation['blocks'] for ref in [*block['subject_refs'],*block['payload'].get('steps',{}),*block['payload'].get('nodes',{})]]
    state.setdefault('presentations',[]).append({'id':key,'ordered_route_refs':refs.encode(selected),'block_refs':[allowed]})
    with service.factory.begin() as session:
        row=service._load(session,workspace_id,lock=True)
        if row.active_turn_id or row.revision!=revision:raise WorkspaceError('浏览期间工作区已改变，请刷新后重试')
        row.state=state;row.revision+=1
        if state.get('pending_action'):state['pending_action']['base_revision']=row.revision;row.state=deepcopy(state)
        return service._view(session,row)
