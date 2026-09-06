"""Whitelisted comparison dimensions with server-owned fact projections."""
COLUMNS={'cost':'费用','steps':'路径步骤','challenge':'挑战要求','eligibility':'资格核对','window':'申请期限','validity':'会籍有效期'}


def comparison_rows(routes,steps,columns):
    if any(column not in COLUMNS for column in columns):raise ValueError('Unsupported comparison dimension')
    columns=list(dict.fromkeys(columns or ['cost','steps','challenge','eligibility']))
    rows=[]
    for column in columns:
        cells=[]
        for route in routes:
            path=[steps[ref] for ref in route['step_refs']]
            if column=='steps':value=[route['from'] or '公开申请',*[step['to'] for step in path]]
            elif column in {'window','validity'}:
                field='application_window' if column=='window' else 'status_validity'
                value=[{'step':step['to'],'value':step.get(field)} for step in path]
            else:value=route[column if column!='cost' else 'cost']
            cells.append(value)
        rows.append({'key':column,'label':COLUMNS[column],'cells':cells})
    return rows


def requested_columns(question,selected):
    import re
    patterns={'cost':r'费用|价格|金额|cost|price|fee','steps':r'步骤|中转|steps|transit',
              'challenge':r'挑战|challenge','eligibility':r'资格|条件|eligibility',
              'window':r'申请期限|申请日期|截止|deadline|application window',
              'validity':r'有效期|有效多久|validity|valid for'}
    explicit=[key for key,pattern in patterns.items() if re.search(pattern,question,re.I)]
    return list(dict.fromkeys([*selected,*explicit])) or ['cost','steps','challenge','eligibility']


def comparison_requested(question):
    import re
    return bool(re.search(r'比较|对比|compare|comparison',question,re.I)) and not re.search(r'用图|图示|图谱|关系图|推荐图|子图|卡片|as a graph|as cards',question,re.I)


def resolve_comparison_scope(question,subject_refs,presentations,refs,routes):
    """Resolve explicit selected objects or an unambiguous 'these two routes'."""
    import re
    if not comparison_requested(question):return []
    if re.search(r'另外|新目标|改成|换成|改为|再加|再和|再与|第三|another|instead|add|third',question,re.I):return []
    explicit=list(dict.fromkeys(ref for ref in refs.decode(subject_refs) if ref in routes))
    if len(explicit)>=2:return explicit[:3]
    if not re.search(r'这两条|这两种|两条路线|两条路径|these two (?:routes|paths)',question,re.I):return []
    for presentation in reversed(presentations):
        candidates=list(dict.fromkeys(refs.decode(item['ref']) for item in presentation['objects'] if item['type']=='route'))
        if len(candidates)==2 and all(ref in routes for ref in candidates):return candidates
    return []


def current_target_comparison(state,refs):
    """Preserve one disclosed representative of each explicitly queried target."""
    if not comparison_requested(state.get('current_question','')):return []
    groups={}
    for group in state.get('current_target_searches',[]):
        target=tuple(group['target'])
        if any(target):groups[target]=group['route_refs']
    if len(groups)<2:return []
    chosen=[]
    for candidates in groups.values():
        visible=[state['routes'][ref] for ref in candidates if ref in refs.reverse and ref in state['routes']]
        if not visible:continue
        from journeyplus.agent.recommendation import recommendation_subset
        chosen.append(recommendation_subset(visible)[0]['ref'])
    return chosen[:3] if len(chosen)>=2 else []
