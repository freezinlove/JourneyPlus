"""Deterministic bounded disclosure; never truncate strings or serialized JSON."""
import json


from journeyplus.knowledge.transport import ModelDecisionPacket,DecisionData,validated_packet

MODEL_FIELDS=set(ModelDecisionPacket.model_fields)
MODEL_DATA_FIELDS=set(DecisionData.model_fields)


def project_model_packet(result):
    # Project before copying or budgeting so a complete search cache neither leaks
    # into the prompt nor consumes the decision packet's disclosure allowance.
    selected={key:value for key,value in result.items() if key in MODEL_FIELDS}
    if isinstance(selected.get('data'),dict):
        selected['data']={key:value for key,value in selected['data'].items() if key in MODEL_DATA_FIELDS}
    packet=validated_packet(selected)
    data=packet.get('data',{})
    if data.get('cards') and isinstance(data.get('query'),dict) and data.get('steps') and not data.get('view'):
        # Overview carries all limiting text once, shared by exact references.
        # Detailed check inputs and evidence are available through INSPECT.
        caveats={};reverse={}
        for item in [*data['cards'],*data['steps'].values()]:
            refs=[]
            for value in item.pop('material_caveats',[]):
                if value not in reverse:
                    ref=f'C{len(caveats)+1}';reverse[value]=ref;caveats[ref]=value
                refs.append(reverse[value])
            item['material_caveat_refs']=list(dict.fromkeys(refs))
            item.pop('fact_refs',None)
        temporals={};temporal_keys={}
        for step in data['steps'].values():
            step.pop('constraint_checks',None)
            for field in ('application_window','status_validity'):
                value=step.get(field)
                if not isinstance(value,dict):continue
                key=json.dumps(value,sort_keys=True,ensure_ascii=False)
                if key not in temporal_keys:
                    ref=f'T{len(temporals)+1}';temporal_keys[key]=ref;temporals[ref]=value
                step.pop(field);step[field+'_ref']=temporal_keys[key]
        data['view']='ROUTE_OVERVIEW';data['material_caveats']=caveats
        data['temporal_facts']=temporals
        packet.setdefault('caveats',[]).append('路线与步骤的 material_caveat_refs 指向 data.material_caveats 中的完整限制；application_window_ref/status_validity_ref 指向 data.temporal_facts 中的完整期限，必须一并读取。逐项资格检查与证据需用 INSPECT 展开，概览不代表无条件可申请。')
    return packet


def encoded_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def input_breakdown(context,packets):
    """Byte measurements of components, not estimated or fabricated token usage."""
    result={'workspace_bytes':encoded_bytes(context),'catalog_bytes':0,'candidate_bytes':0,'materials_bytes':0,'evidence_bytes':0,'facts_bytes':0,
            'tool_packet_bytes':encoded_bytes(packets),'tool_statuses':[p.get('status') for p in packets]}
    for packet in packets:
        data=packet.get('data',{})
        for label,keys in [('catalog_bytes',('catalog',)),('candidate_bytes',('cards','routes','steps','groups','material_caveats','temporal_facts')),
                           ('materials_bytes',('activities','facts','snippets','changes')),
                           ('evidence_bytes',('snippets',)),('facts_bytes',('activities','facts','changes'))]:
            selected={key:data[key] for key in keys if key in data}
            if selected:result[label]+=encoded_bytes(selected)
    return result


def decision_packets(packets,*,max_bytes=21000):
    """One budget for the entire tool history, with exact duplicate removal."""
    if max_bytes<3000:raise ValueError('Tool history budget must be at least 3000 bytes')
    unique=[];seen=set();catalogs=set()
    for original in reversed(packets):
        packet=project_model_packet(original)
        key=json.dumps(packet,sort_keys=True,ensure_ascii=False)
        if key in seen:continue
        seen.add(key)
        data=packet.get('data',{})
        if data.get('catalog'):
            catalog=json.dumps(data['catalog'],sort_keys=True,ensure_ascii=False)
            if catalog in catalogs:data.pop('catalog')
            else:catalogs.add(catalog)
        unique.append(packet)
    unique.reverse()
    if encoded_bytes(unique)<=max_bytes:
        return [decision_packet(packet,max_bytes=max_bytes) for packet in unique]
    remaining=max_bytes-len(unique)-2;out=[]
    for index in range(len(unique)-1,-1,-1):
        budget=max(600,remaining-1000*index)
        packet=decision_packet(unique[index],max_bytes=budget)
        if encoded_bytes(packet)>budget:
            packet={'schema_version':1,'status':'NEEDS_INSPECTION','snapshot_ref':unique[index].get('snapshot_ref'),
                    'data':{},'coverage':{'content_complete':False,'search_complete':False},
                    'caveats':['本轮总预算未展开这份资料；不能据此断言没有条件或没有其他方案。']}
        out.append(packet);remaining-=encoded_bytes(packet)
    out.reverse()
    if encoded_bytes(out)>max_bytes:
        raise ValueError('Too many tool results for the configured input budget')
    return out


def decision_packet(result: dict, *, max_bytes: int = 15000) -> dict:
    """Keep atomic facts/cards; an omitted item remains explicitly inspectable.

    Byte ceilings are conservative input limits, not claims about provider tokens.
    Source sections are one atomic group because a footnote can reverse a rule.
    """
    # This boundary is deliberately allow-listed: complete server search caches
    # and internal snapshots must never reach the model even from a new caller.
    packet = project_model_packet(result)
    omitted = []
    if encoded_bytes(packet) <= max_bytes:
        return packet
    data = packet.get('data', {})
    # Do not split a table from its exceptions just to satisfy an input budget.
    if data.get('snippets'):
        omitted.extend({'ref': x['ref'], 'kind': 'SECTION'} for x in data['snippets'])
        data['snippets'] = []
    for key in ('changes', 'facts', 'cards', 'routes', 'activities','groups','step_observations','research_steps','official_rechecks'):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        while items and encoded_bytes(packet) > max_bytes - 1200:
            item = items.pop()
            if isinstance(item, dict) and item.get('ref'):
                omitted.append({'ref': item['ref'], 'kind': key.upper()})
            else:
                omitted.append({'kind':key.upper(),'reason':'使用续页或限定目标继续读取'})
            if isinstance(data.get('steps'),dict) and ('cards' in data or 'routes' in data):
                used={sid for card in data.get('cards',[])+data.get('routes',[]) for sid in card.get('step_refs',[])}
                data['steps']={sid:step for sid,step in data['steps'].items() if sid in used}
    if omitted:
        packet['status'] = 'PARTIAL'
        packet.setdefault('caveats', []).append('内容预算限制：部分完整资料尚未展开；不能据此判断没有限制或没有其他方案。')
        packet.setdefault('coverage', {}).update(presentation_has_more=True, content_complete=False, content_stopped_reason='MODEL_INPUT_BUDGET')
        unique_expansions={}
        for expansion in packet.get('expansions', []) + omitted:
            identity=expansion.get('ref') or json.dumps(expansion,sort_keys=True)
            unique_expansions.setdefault(identity,expansion)
        packet['expansions'] = list(unique_expansions.values())
        packet['omitted_item_count'] = len(omitted)
        if 'cards' in data:
            packet['coverage']['disclosed_candidate_count']=len(data['cards'])
            packet['caveats'].append('本页被省略的候选仍在 expansions 中；要完整遍历，先按引用 INSPECT 这些候选，再使用 next_cursor，不能把下一页当作本页省略项。')
    if encoded_bytes(packet) > max_bytes:
        # A single indivisible record can exceed the budget. Fail closed, preserving
        # the exact snapshot and the query scope instead of sending a partial rule.
        references=[{'ref':entry['ref'],'kind':entry.get('kind','OBJECT')} for entry in packet.get('expansions',[]) if entry.get('ref')]
        fallback={'schema_version': 1, 'status': 'NEEDS_INSPECTION', 'snapshot_ref': packet.get('snapshot_ref'),
                'next_cursor':packet.get('next_cursor'),
                'data': {'catalog':data['catalog']} if data.get('catalog') and encoded_bytes(data['catalog'])<max_bytes//2 else {}, 'coverage': {**packet.get('coverage', {}), 'content_complete': False},
                'caveats': ['完整事实对象超出预算；已保留的 catalog 仍是有效项目/等级身份，可直接用于路径查询。事实需按引用展开，不能把下一页当作本页省略项。'],
                'expansions':references}
        if encoded_bytes(fallback)>max_bytes:
            # If even all page references cannot fit, never expose a cursor
            # that skips undisclosed candidates on the current page.
            fallback['next_cursor']=None
            fallback['coverage']={'search_complete':False,'content_complete':False,'presentation_has_more':True,
                                  'undisclosed_reference_count':0,'content_stopped_reason':'MODEL_INPUT_BUDGET'}
            fallback['caveats']=['引用也超过预算；不能跳过本页，请缩小查询范围后重查。']
            while fallback['expansions'] and encoded_bytes(fallback)>max_bytes:
                fallback['expansions'].pop()
                fallback['coverage']['undisclosed_reference_count']+=1
        return fallback
    return packet
