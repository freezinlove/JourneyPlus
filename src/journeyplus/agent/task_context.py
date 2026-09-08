"""Small temporary query scope; unrestricted is a value, not missing input."""
import re
from copy import deepcopy
from journeyplus.agent.completion import explicit_public_opportunity_request, explicit_route_assessment


def broad_reply(text):
    broad=bool(re.search(r'所有|全部|任意|不限|随便|都要|\ball\b|\bany\b|\bboth\b',text,re.I))
    business=bool(re.search(r'路径|路线|活动|会籍|项目|酒店|航司|航空|routes?|paths?|programmes?|programs?|airlines?|hotels?',text,re.I))
    short=bool(re.fullmatch(r'\s*(?:我说了)?(?:所有|全部|任意|随便|不限|都)(?:的)?(?:都)?(?:要|行|可以|给我列出来)?[，,。.!！\s]*',text))
    return (broad and business) or short


def explicit_unrestricted_reply(text):
    # Only a standalone reply has an unambiguous scope here. Longer natural
    # language (including "all paths to X") is interpreted by the normal model
    # decision, never by a keyword that silently deletes constraints.
    return bool(re.fullmatch(r'\s*(?:我说了)?(?:所有|全部|任意|随便|不限|都)(?:的)?(?:都)?(?:要|行|可以|给我列出来)?[，,。.!！\s]*',text))


def explicit_target_reset(text):
    """A complete, unqualified reset clause; never matches 'all paths to X'."""
    match=re.fullmatch(r'\s*(?:目标不限|不限目标|目标不限制|不限制目标)(?:[，,。\s]*(?:所有|全部)?(航司|航空公司|酒店|项目)(?:都)?(?:可以|行|要))?[。.!！\s]*',text)
    if not match:return None
    category={'航司':'AIRLINE','航空公司':'AIRLINE','酒店':'HOTEL'}.get(match[1])
    return {'category':category} if category else {}


def prepare_task(state,text):
    old=state.get('task_context',{})
    reset=explicit_target_reset(text)
    new_route=explicit_route_assessment(text) and not explicit_public_opportunity_request(text)
    new_source=bool(re.search(r'我有|我持有|我是|我现在是|假设.*有|I (?:have|hold|am)',text,re.I))
    state['source_update_applied']=False
    state['replaced_source_ids']=[]
    state['source_change_requested']=new_source
    if new_source:state['source_identity_pending']=True
    state['target_change_requested']=False
    reuse_route=old.get('intent')=='ROUTES' and not new_source
    broad_route=bool(explicit_unrestricted_reply(text) and state.get('unresolved_question',{}).get('field')!='SOURCE_PROGRAM' and old.get('target_scope')!='SELECTED' and old.get('category_scope')!='SELECTED' and (new_route or old.get('intent')=='ROUTES')
                     and not re.search(r'保存|修改|更新|取消|先不聊|换个话题',text))
    continuing=bool(old.get('intent')=='PUBLIC_OPPORTUNITIES' and old.get('target_scope')!='SELECTED' and old.get('category_scope')!='SELECTED' and state.get('unresolved_question',{}).get('field')!='SOURCE_PROGRAM' and explicit_unrestricted_reply(text) and not re.search(r'保存|修改|更新|取消|先不聊|换个话题',text))
    public=explicit_public_opportunity_request(text) or continuing
    if explicit_public_opportunity_request(text):
        state['task_context']={'intent':'PUBLIC_OPPORTUNITIES','target_scope':'UNSPECIFIED','category_scope':'UNSPECIFIED','hypothetical_empty':True}
    elif continuing:
        state['task_context']={**old,'target_scope':'ANY','category_scope':'ANY'}
    elif broad_route:
        state['task_context']={**old,'intent':'ROUTES','target_scope':'ANY','category_scope':'ANY','hypothetical_empty':False}
        if not reuse_route:
            # A new source must be resolved before execution, never reuse the
            # previous task's starting tier just because targets are broad.
            state['query']=None
        elif state.get('query'):
            state['query']={**state['query'],'target_program_id':None,'target_tier_id':None,'alliance':None,'category':None}
    elif new_route:
        state['task_context']={**old,'intent':'ROUTES','hypothetical_empty':False}
        if new_source:
            # Resolve a fresh source without deleting the existing destination.
            prior=state.get('query') or {}
            state['query']={**prior,'starting_tier_ids':[],'use_saved_holdings':False} if prior else None
    if broad_route or continuing:state['target_change_requested']=True
    # Only current public requests/clear replies inherit execution guards.
    # Unrelated chatter is not forced into the old task.
    state['public_task_active']=public
    state['route_task_active']=new_route or broad_route or (old.get('intent')=='ROUTES' and broad_reply(text))
    state['unrestricted_route_active']=broad_route
    state['explicit_broad_reply']=continuing or (broad_route and reuse_route and bool(state.get('query')))
    if public:
        query=deepcopy(state.get('query') or {}) if continuing else {}
        query.update(use_saved_holdings=False,starting_tier_ids=[])
        if continuing:query.update(target_program_id=None,target_tier_id=None,alliance=None,category=None)
        state['query']=query
    if reset is not None and old.get('intent') in {'ROUTES','PUBLIC_OPPORTUNITIES'}:
        # Clearing a named slot is different from asking for every result
        # within its current value. A whole-clause reset can safely reuse IDs.
        context={**old,'target_scope':'ANY'};context.pop('target_text',None)
        query={**(state.get('query') or {}),'target_program_id':None,'target_tier_id':None,'alliance':None}
        if reset.get('category'):
            context['category_scope']='SELECTED';query['category']=reset['category']
        state['task_context']=context;state['query']=query
        state['target_change_requested']=True
        state['route_task_active']=old['intent']=='ROUTES'
        state['unrestricted_route_active']=old['intent']=='ROUTES'
        state['public_task_active']=old['intent']=='PUBLIC_OPPORTUNITIES'
        state['explicit_broad_reply']=bool(query.get('starting_tier_ids') or state['public_task_active']) and not state.get('source_identity_pending')
        public=state['public_task_active']
    return public


def public_scope_question(state,question):
    # The programme of an existing holding is a required identity, unlike
    # a preferred destination. Do not suppress that genuine clarification.
    if re.search(r'起点|(?:你|您).*(?:持有|已有|现有)|(?:卡|等级|会籍).*(?:属于|所属)|which.*(?:hold|existing)',question,re.I):return False
    if state.get('task_context',{}).get('target_scope')=='SELECTED':return False
    return (state.get('public_task_active',False) or state.get('route_task_active',False)) and bool(re.search(
        r'目标|偏好|联盟|哪[一个类种].*(?:项目|航空|酒店|活动|计划)|prefer|target|alliance',question,re.I))


def public_query(state,query):
    """Merge execution constraints; scope metadata never erases supplied IDs."""
    result={**(query or {})}
    scope=state.get('task_context',{})
    previous=state.get('query') or {}
    if state.get('explicit_broad_reply'):
        result.update(target_program_id=None,target_tier_id=None,alliance=None)
    selected=bool(result.get('target_program_id') or result.get('target_tier_id'))
    if selected:
        # Actual validated tool arguments win over a stale/default ANY label.
        state['task_context']={**scope,'target_scope':'SELECTED'}
        state['unrestricted_route_active']=False
        if result.get('target_program_id')==previous.get('target_program_id') and not state.get('target_change_requested'):
            result.setdefault('target_tier_id',previous.get('target_tier_id'))
    elif not state.get('target_change_requested'):
        for key in ('target_program_id','target_tier_id','alliance','category'):
            if result.get(key) is None and previous.get(key) is not None:result[key]=previous[key]
    # Category is an independent filter, including when the destination changes.
    if result.get('category') is None and previous.get('category') is not None:
        result['category']=previous['category']
    if state.get('public_task_active'):result.update(use_saved_holdings=False,starting_tier_ids=[])
    return result


def apply_task_update(state,update,text):
    if update is None or state.get('turn_route_plan'):return
    old=state.get('task_context',{})
    if update.source_changed:
        state['source_change_requested']=True
        if not state.get('source_update_applied'):
            # A change must invalidate the old executable source immediately,
            # not merely give permission to change it in a later tool call.
            prior=dict(state.get('query') or {})
            state['replaced_source_ids']=prior.get('starting_tier_ids',[])[:]
            prior.update(starting_tier_ids=[],use_saved_holdings=False)
            state['query']=prior
            state['source_identity_pending']=True
            state['source_update_applied']=True
    if state.get('explicit_broad_reply'):return
    if state.get('public_task_active') and update.intent!='PUBLIC_OPPORTUNITIES':return
    same_task=old.get('intent')==update.intent
    merged={**(old if same_task else {}), 'intent':update.intent,
            'hypothetical_empty':update.intent=='PUBLIC_OPPORTUNITIES'}
    if update.target_changed:
        state['target_change_requested']=True
        prior=dict(state.get('query') or {})
        for key in ('target_program_id','target_tier_id'):prior.pop(key,None)
        if state.get('query') is not None:state['query']=prior
        merged.pop('target_text',None)
    for field in ('target_scope','category_scope'):
        value=getattr(update,field)
        # UNSPECIFIED is omission, not reset. An ANY default cannot discard
        # a selected target during a source-only clarification.
        if value=='UNSPECIFIED':merged.setdefault(field,'UNSPECIFIED')
        elif field=='target_scope' and value=='ANY' and merged.get(field)=='SELECTED' and not update.target_changed:pass
        else:merged[field]=value
    if update.source_text:merged['source_text']=update.source_text
    if update.source_count is not None:merged['source_count']=update.source_count
    if update.target_text:merged['target_text']=update.target_text
    if merged.get('target_scope')=='ANY':merged.pop('target_text',None)
    state['task_context']=merged
    state['route_task_active']=update.intent=='ROUTES'
    state['unrestricted_route_active']=update.intent=='ROUTES' and merged.get('target_scope')=='ANY'
    state['public_task_active']=update.intent=='PUBLIC_OPPORTUNITIES'
    if update.intent not in {'ROUTES','PUBLIC_OPPORTUNITIES'}:
        state.pop('unresolved_question',None)
        state['source_identity_pending']=False
