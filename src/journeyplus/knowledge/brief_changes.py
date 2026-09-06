"""Deterministic, bounded change previews; full facts stay in bound versions."""
from journeyplus.knowledge.publication import _semantic

LABELS={'summary':'活动说明','conditions':'申请资格','lifecycle':'活动状态','application_window':'申请日期','caveats':'特别限制','prices':'费用','mappings':'会籍映射','challenge':'挑战要求','status_validity':'获批有效期','availability':'申请可用性'}
IMPACTS={'summary':'活动说明已更新，申请条件仍以对应条款为准。','conditions':'可能影响申请资格，已计划的申请需重新核对。','lifecycle':'请按新活动状态判断是否仍可申请。','application_window':'可能影响提交时间，原计划需核对新日期。','caveats':'例外或限制已变化，不能直接沿用旧判断。','prices':'费用或适用范围已变化，原预算需按具体申请方式重新计算。','mappings':'可申请的来源或目标已变化，原路径需重新评估。','challenge':'完成要求已变化，请重新核对所需消费、入住或飞行。','status_validity':'获批会籍的期限已变化，请重新核对使用计划。','availability':'这项申请方式的可用性已变化。'}


def stable(value):
    if isinstance(value,dict):return {k:stable(v) for k,v in _semantic(value).items() if k not in {'ref','evidence_ids'}}
    if isinstance(value,list):
        import json
        return sorted([stable(v) for v in value],key=lambda v:json.dumps(v,sort_keys=True,ensure_ascii=False))
    return " ".join(value.split()) if isinstance(value,str) else value


def preview(field,value,option=None):
    if field=='prices':
        targets={m['target_tier_id']:m['to_tier'] for m in (option or {}).get('mappings',[])}
        items=[{'target':targets.get(p.get('target_tier_id'),'该申请方式范围内等级'),'known_state':p['known_state'],'amount':p.get('amount'),'currency':p.get('currency'),'fee_role':p.get('fee_role'),'availability':p.get('availability'),'combination':p.get('combination'),'conditions':p.get('conditions')} for p in value]
    elif field=='mappings':
        items=[{'source':m.get('from_tier') or m.get('source_kind','来源待核实'),'target':m.get('to_tier','目标待核实')} for m in value]
    else:return value
    return {'items':items[:6],'count':len(items),'omitted':max(0,len(items)-6)}


def changes_between(previous,detail):
    changes=[]
    for field in ('summary','conditions','lifecycle','application_window','caveats'):
        old=previous['facts'].get(field);new=detail['facts'].get(field)
        if stable(old)!=stable(new):changes.append({'scope':'ACTIVITY','path':f'facts.{field}','label':LABELS[field],'impact':IMPACTS[field],'before':old,'after':new})
    before={o['logical_ref']:o for o in previous['options']};after={o['logical_ref']:o for o in detail['options']}
    for identity in sorted(before.keys()|after.keys()):
        old=before.get(identity);new=after.get(identity)
        if old is None or new is None:
            changes.append({'scope':'OPTION','logical_ref':identity,'change':'ADDED' if old is None else 'REMOVED','label':(new or old)['label'],'impact':'新增申请方式，需核对来源、费用和资格。' if old is None else '此版本已不再包含该申请方式，旧路线不能直接沿用。'});continue
        for field in ('prices','mappings','conditions','challenge','application_window','status_validity','availability'):
            if stable(old[field])!=stable(new[field]):changes.append({'scope':'OPTION','logical_ref':identity,'path':field,'before_ref':old['ref'],'after_ref':new['ref'],'label':new['label']+' · '+LABELS[field],'impact':IMPACTS[field],'before':preview(field,old[field],old),'after':preview(field,new[field],new)})
    for change in changes:
        old=change.get('before');new=change.get('after')
        if change.get('path') in {'conditions','facts.conditions'} and isinstance(old,dict) and isinstance(new,dict):
            def texts(value):return sorted(' '.join(i.get('raw_text','').split()) for i in value.get('items',[]))
            if texts(old) and texts(old)==texts(new):
                change['change']='INTERPRETATION_UPDATED'
                change['impact']='来源中的相关原文未改变，本次修正资料判读；不代表官方发布了新的申请规则。旧路径判断应重新核对。'
                topics={'RESIDENCY':'居住地条件','DOCUMENT_REQUIREMENT':'证件要求','SOURCE_STATUS':'来源会籍要求','PRIOR_PARTICIPATION':'历史参与限制'}
                def interpretation(value):
                    return '；'.join(f"{topics.get(i.get('topic'),i.get('topic','申请条件'))}：{i.get('raw_text','')}" for i in value.get('items',[]))
                change['before']=interpretation(old);change['after']=interpretation(new)
        change.update(before_version_ref=previous['version_ref'],after_version_ref=detail['version_ref'])
    return changes
