"""Version-bound activity previews shared by browse and Agent surfaces."""
from decimal import Decimal
from collections import defaultdict,deque


def activity_card(detail):
    fees=[];challenges=[]
    for option in detail.get('options',[]):
        challenge=option.get('challenge',{})
        challenges.append(challenge.get('value',{}).get('kind','UNKNOWN') if challenge.get('known_state')=='KNOWN' else 'UNKNOWN')
        names={m['target_tier_id']:m['to_tier'] for m in option.get('mappings',[])}
        for price in option.get('prices',[]):
            label=option['label']+' · '+names.get(price.get('target_tier_id'),'该方案范围内等级')
            if price['known_state']=='KNOWN' and price.get('amount') is not None:
                amount=Decimal(price['amount'])
                value='免费' if amount==0 else f"{price.get('currency') or ''} {format(amount.normalize(),'f')}".strip()
            else:value='费用待核实' if price['known_state']!='CONFLICT' else '费用来源冲突'
            caveats=[]
            if price.get('availability')!='AVAILABLE':caveats.append('适用性待核实')
            if price.get('combination') in {'CONDITIONAL','ALTERNATIVE'} or price.get('conditions',{}).get('items'):caveats.append('附适用条件')
            role={'APPLICATION':'申请费','BUY_UP':'升级附加费','CHALLENGE_SPEND':'挑战消费','OTHER':'其他费用'}.get(price.get('fee_role'),'费用')
            fees.append({'ref':price['ref'],'label':label,'value':value,'role':role,'caveats':caveats,
                         '_currency':price.get('currency'),'_target':price.get('target_tier_id')})
    queues=defaultdict(deque);seen=set()
    for fee in fees:
        key=(fee['_target'],fee['_currency'],fee['value'],fee['role'],tuple(fee['caveats']))
        if key in seen:continue
        seen.add(key);queues[fee['_currency']].append(fee)
    selected=[]
    while any(queues.values()) and len(selected)<3:
        for queue in queues.values():
            if queue and len(selected)<3:selected.append(queue.popleft())
    lifecycle=detail.get('facts',{}).get('lifecycle',{})
    return {'version_ref':detail.get('version_ref'),'kind':detail.get('kind'),
        'lifecycle':lifecycle.get('value') if lifecycle.get('known_state')=='KNOWN' else 'UNKNOWN',
        'fees':[{k:v for k,v in fee.items() if not k.startswith('_')} for fee in selected],
        'additional_fee_count':len(fees)-len(selected),
        'challenge':'UNKNOWN' if not challenges or 'UNKNOWN' in challenges else 'NONE' if all(c=='NONE' for c in challenges) else 'REQUIRED',
        'eligibility_note':'不同申请方式的资格及适用限制，请在详情中逐项核对。',
        'fee_note':None if fees else '尚无已核实费用，不能据此推断免费。'}


def focused_activity_card(detail,question):
    """Use exact disclosed tier names to keep a question's preview relevant."""
    import re
    from copy import deepcopy
    targets={m['target_tier_id'] for o in detail.get('options',[]) for m in o.get('mappings',[])
             if len(m.get('to_tier',''))>=4 and re.search(r'(?<!\w)'+re.escape(m['to_tier'])+r'(?!\w)',question,re.I)}
    if not targets:return activity_card(detail)
    selected=deepcopy(detail)
    selected['options']=[o for o in selected.get('options',[]) if any(m['target_tier_id'] in targets for m in o.get('mappings',[]))]
    for option in selected['options']:
        option['mappings']=[m for m in option['mappings'] if m['target_tier_id'] in targets]
        option['prices']=[p for p in option.get('prices',[]) if p.get('target_scope')!='EXACT' or p.get('target_tier_id') in targets]
    return activity_card(selected)
