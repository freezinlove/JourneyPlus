"""Resolve conversational route edits once, before resolving database identities.

This replaces the first large tool decision; it does not add a classifier on
 top of the existing three-call route workflow. Text never grants an identity.
"""
from typing import Literal
from pydantic import Field,field_validator
from journeyplus.agent.workspace_contracts import StrictModel


class IdentityLookup(StrictModel):
    text: str = Field(min_length=1,max_length=160,description='仅会籍项目名，不含等级，等级另填tier；只知道等级时保留等级，不猜项目')
    alternate_names: list[str] = Field(min_length=1,max_length=3,description='必填项目检索规范名，不含等级：中文/简称须提供确定的英文品牌、官方项目名或缩写；已经是正式名或确实不知道对应名时重复原词，不能凭空猜其他项目')
    tier: str | None = Field(default=None,max_length=100,description='用户给出的等级，可继承同一项目此前明确的等级；不同项目不能沿用等级')

    @field_validator('alternate_names',mode='before')
    @classmethod
    def bound_lookup_terms(cls,value):
        # Extra synonyms are retrieval hints, not extra identities or actions.
        # Deduplicate and cap them without spending a model call on formatting.
        if isinstance(value,list) and all(isinstance(x,str) for x in value):
            return list(dict.fromkeys(x.strip() for x in value if x.strip()))[:3]
        return value


class RouteTurnPlan(StrictModel):
    kind: Literal['ROUTES','OTHER']
    source_action: Literal['KEEP','REPLACE']
    sources: list[IdentityLookup] = Field(default_factory=list,max_length=10)
    target_action: Literal['KEEP','SELECT','ANY']
    target: IdentityLookup | None = None
    request: str = Field(min_length=1,max_length=400,description='本轮要执行的简短完整问题，明确起点和目标范围，不包含推理过程')


PROMPT='''你只负责理解用户最新一句对当前会籍路径查询做了什么改变，输出一个简短查询计划，不查规则、不回答、不生成数据库ID。
latest_user_input 才是本轮请求；previous_query、previous_task 和 history 都是此前背景。先理解最新输入，再继承没改的部分，不要照抄旧查询。
ROUTES 用于路径查询、换起点、换目标及继续探索。闲聊、费用/条款细节、预算/条件筛选、具体步骤、路径比较、保存、经验调查等其他任务用 OTHER，由原工具流程处理。
source_action=REPLACE：本轮提供/更换起点，包括对话里的省略句“另一项目金卡呢”；sources填写要用的项目和等级。source_action=KEEP：只改目标、比较/浏览当前结果，sources为空。
已在查 A 金到 B 时，“C 金呢”通常是换起点到 C 金，保留目标 B。只有明确说匹配到/只看/目标 C 才是改目标。不能因为新句没有“我有”就忽略新会籍。
“把 A 的所有匹配路径给我”表示从 A 出发重新看全部机会（target_action=ANY）；若 A 是之前说过的起点，继承那个项目的明确等级；不能继续限定旧目标 B。“所有都要”只表示当前范围内全要（KEEP）。“所有到 B 的路径”限定 B（SELECT）。
一次允许同时更换起点和目标范围；不得只更新一项。target_action=SELECT 时填写目标项目及用户实际指定的等级；ANY取消目标项目，target为空；KEEP继承当前目标。
项目只是检索词。目录主要存英文正式名，每个项目的 alternate_names 必须包含你确定的英文品牌、官方项目名或缩写，中文原词单独查询可能没有结果。已是正式名或确实不知道对应名时重复原词，不编造翻译。只说金卡/Gold不能猜某项目；等级未知时tier=null，不能猜用户持有更高等级。用户已经给出等级，不要忽略。历史中已明确过等级的同一项目可以恢复其等级。
request写合并后的简短完整请求，用于后续执行一致性，不写思考分析。'''


def apply_plan(service,plan,state,packets,basis,emit):
    """Apply the edit and perform bounded independent catalogue reads."""
    from time import monotonic
    from journeyplus.agent.workspace import now_utc,read_basis,WorkspaceError
    if plan.kind=='OTHER':
        state['route_task_active']=False
        return None
    previous_query=state.get('query') or {}
    previous_scope=state.get('task_context') or {}
    if plan.source_action=='KEEP' and not previous_query.get('starting_tier_ids') and state.get('source_identity_pending') and previous_scope.get('source_lookups'):
        plan=plan.model_copy(update={'source_action':'REPLACE','sources':[IdentityLookup.model_validate(x) for x in previous_scope['source_lookups']]})
    if plan.target_action=='KEEP' and previous_scope.get('target_scope')=='SELECTED' and not (previous_query.get('target_program_id') or previous_query.get('target_tier_id')):
        target=plan.target or (IdentityLookup.model_validate(previous_scope['target_lookup']) if previous_scope.get('target_lookup') else None) or (IdentityLookup(text=previous_scope['target_text'],alternate_names=[previous_scope['target_text']]) if previous_scope.get('target_text') else None)
        if target:plan=plan.model_copy(update={'target_action':'SELECT','target':target})
    if plan.source_action=='REPLACE' and not plan.sources:raise WorkspaceError('新起点计划缺少身份检索词')
    if plan.target_action=='SELECT' and plan.target is None:raise WorkspaceError('新目标计划缺少身份检索词')
    state['turn_route_plan']=plan.model_dump(mode='json')
    state['route_task_active']=True;state['public_task_active']=False
    scope=dict(state.get('task_context') or {});scope['intent']='ROUTES'
    query=dict(state.get('query') or {})
    if plan.source_action=='REPLACE':
        state['source_change_requested']=True;state['source_identity_pending']=True
        state['replaced_source_ids']=query.get('starting_tier_ids',[])[:]
        query.update(starting_tier_ids=[],use_saved_holdings=False)
        scope['source_count']=len(plan.sources)
        scope['source_lookups']=[x.model_dump(mode='json') for x in plan.sources]
        scope['source_text']='、'.join(f'{x.text} {x.tier or ""}'.strip() for x in plan.sources)
    if plan.target_action!='KEEP':
        state['target_change_requested']=True
        query.update(target_program_id=None,target_tier_id=None,alliance=None)
        scope['target_scope']='ANY' if plan.target_action=='ANY' else 'SELECTED'
        scope.pop('target_text',None)
        scope.pop('target_lookup',None)
        if plan.target:
            scope['target_text']=f'{plan.target.text} {plan.target.tier or ""}'.strip()
            scope['target_lookup']=plan.target.model_dump(mode='json')
    state['task_context']=scope;state['query']=query
    state['unrestricted_route_active']=scope.get('target_scope')=='ANY'
    lookups=[('source',x) for x in plan.sources] if plan.source_action=='REPLACE' else []
    if plan.target_action=='SELECT':lookups.append(('target',plan.target))
    missing_source=False
    for role,identity in lookups:
        args={'view':'CATALOG','selector':{'text':identity.text,'alternate_names':identity.alternate_names},'question':plan.request}
        started=monotonic();emit('phase',{'label':'正在确认会籍项目与等级'})
        packet=service._tool('query_activity_materials',args,state,plan.request)
        packets.append(packet)
        receipt=read_basis('query_activity_materials',packet)
        receipt.update(view='CATALOG',role=role,elapsed_ms=round((monotonic()-started)*1000),read_at=now_utc().isoformat())
        basis.append(receipt)
        programs=packet.get('data',{}).get('catalog',{}).get('programs',[])
        state.setdefault('planned_'+role+'_programs',[]).extend(p['id'] for p in programs)
        if role=='source':
            from journeyplus.knowledge.publication import canonical_key
            key=canonical_key(identity.tier or '')
            matching=[t['id'] for p in programs for t in p['tiers'] if key and key in {canonical_key(t['name']),*(canonical_key(a['name']) for a in t.get('aliases',[]))}]
            state.setdefault('planned_source_tier_groups',[]).append(matching)
        if role=='source' and packet.get('missing_input')=='SOURCE_PROGRAM':missing_source=True
    if missing_source:
        question='这张会籍属于哪个酒店或航空项目？需要先确认起点，才能查对应的匹配路径。'
        state['unresolved_question']={'field':'SOURCE_PROGRAM','text':question}
        return {'text':question,'blocks':[],'next_steps':[]}
    return None


class RouteIdentitySelection(StrictModel):
    starting_tier_refs: list[str] = Field(default_factory=list,max_length=10)
    target_program_ref: str | None = None
    target_tier_ref: str | None = None
    clarification: str | None = Field(default=None,max_length=300,description='确实无法确定身份时只澄清具体缺失项目/等级；有足够目录信息就留空')
    clarification_field: Literal['SOURCE_PROGRAM','SOURCE_TIER','TARGET_IDENTITY'] = 'SOURCE_TIER'


RESOLVE_PROMPT='''根据 route_plan 和 catalog 只选择本轮发生改变的起点及目标的已披露引用。只做身份选择，不能请求再次读取同一目录，也不能改变查询计划。
REPLACE 的起点选 sources 对应项目的准确等级，不能选旧起点。KEEP 的起点返回空列表，后端自动保留原起点，无需复制。SELECT 的目标使用 plan.target 对应项目；KEEP 和 ANY 的目标引用为空，由后端保留或清除。起点等级与目标项目引用不能交换。没有指定目标等级不要擅自加等级限制。
一个会籍只选择一个对应等级，不把所有候选都选入。目录中的明确名称和 aliases 是身份依据；登记的别名优先于自身常识，不能按目录排序猜金银等级。目录中的明确名称及已知简称可用于辨别身份；真正无法区分时用 clarification 问唯一缺口，不问可选目标偏好。query 已有的目标引用无需重复检索。输出中所有引用必须来自给定目录或 query，不能自造。'''


def execute_selection(service,selection,state,refs,basis,packets,emit):
    from time import monotonic
    from journeyplus.agent.workspace import read_basis,now_utc,WorkspaceError
    if selection.clarification:
        state['unresolved_question']={'field':selection.clarification_field,'text':selection.clarification}
        return {'text':selection.clarification,'blocks':[],'next_steps':[]}
    plan=state['turn_route_plan'];query=dict(state.get('query') or {})
    # Unchanged fields belong to the server's plan, not model reproduction.
    # Ignore irrelevant suggestions before decoding; they grant no identity.
    raw={'starting_tier_ids':selection.starting_tier_refs if plan['source_action']=='REPLACE' else [],
         'target_program_id':selection.target_program_ref if plan['target_action']=='SELECT' else None,
         'target_tier_id':selection.target_tier_ref if plan['target_action']=='SELECT' else None}
    refs.require_disclosed(raw)
    values=refs.decode(raw)
    if plan['source_action']=='REPLACE':
        if not values['starting_tier_ids']:raise WorkspaceError('起点计划尚未解析出等级，不能执行空起点')
        query.update(starting_tier_ids=values['starting_tier_ids'],use_saved_holdings=False)
    if plan['target_action']=='SELECT':
        query.update(target_program_id=values['target_program_id'],target_tier_id=values['target_tier_id'])
    elif plan['target_action']=='ANY':query.update(target_program_id=None,target_tier_id=None)
    started=monotonic();emit('phase',{'label':'正在查询匹配路径'})
    result=service._tool('query_membership_routes',{'mode':'EXPLORE','query':query},state,plan['request'])
    packets.append(result);receipt=read_basis('query_membership_routes',result)
    receipt.update(view='EXPLORE',read_at=now_utc().isoformat(),elapsed_ms=round((monotonic()-started)*1000),cache_hit=result.get('cache_hit',False))
    basis.append(receipt)
    return None
