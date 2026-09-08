"""Resolve a clicked object's deictic follow-up without changing query scope."""
import re


def focused_qualification(state,refs,question,subject_refs=()):
    if not re.search(r'证件|护照|条件|资格|要求|核实',question):return None
    if re.search(r'比较|对比|另外|其他|两条|全部',question):return None
    explicit=[r for r in refs.decode(list(subject_refs)) if r in state.get('routes',{})]
    if explicit:
        return {'routes':list(dict.fromkeys(explicit))[:3],'steps':list(dict.fromkeys(s for r in explicit[:3] for s in state['routes'][r]['step_refs']))[:6]}
    if re.search(r'^(?:那)?(?:这条路径|这条路线|这个方案|还要|还需要)',question.strip()):
        last=next((p for p in reversed(state.get('presentations',[])) if p.get('ordered_route_refs')),None)
        visible=refs.decode(last['ordered_route_refs']) if last else []
        routes=[r for r in visible if r in state.get('routes',{})]
        if len(routes)==1:return {'routes':routes,'steps':state['routes'][routes[0]]['step_refs'][:6]}
        return None
    if not re.search(r'^(?:那)?(?:这个|这一步|该节点|这个节点)',question.strip()):return None
    focus=state.get('focus') or {}
    raw=refs.decode(focus.get('ref'))
    step_refs=state.get('nodes',{}).get(raw,{}).get('step_refs',[])
    if raw in state.get('steps',{}):step_refs=[raw]
    if raw in state.get('routes',{}):step_refs=state['routes'][raw]['step_refs']
    if not step_refs:return None
    presentation=next((p for p in state.get('presentations',[]) if p['id']==focus.get('presentation_id')),None)
    if not presentation:return None
    visible=refs.decode(presentation.get('ordered_route_refs',[]))
    routes=[r for r in visible if set(state.get('routes',{}).get(r,{}).get('step_refs',[])).intersection(step_refs)]
    return {'routes':list(dict.fromkeys(routes))[:3],'steps':list(dict.fromkeys(step_refs))[:6]} if routes else None
