"""Diverse candidate order without lossy dominance or implicit exchange rates."""
from collections import defaultdict,deque
from decimal import Decimal


def _uncertainty(route):
    return (len(route['unknowns'])+int(route['cost']['state']!='KNOWN')+
            int(route['challenge']=='UNKNOWN')+int(route.get('eligibility')=='UNKNOWN'),
            len(route['material_caveats']),route['step_count'],route['ref'])


def order_candidates(routes,preferences=()):
    groups=defaultdict(list)
    for route in routes:
        row={**route,'selection_reasons':[]}
        groups[(row['to'],row['classification'])].append(row)
    queues={};overview=[]
    for (target,classification),items in sorted(groups.items()):
        stable=sorted(items,key=lambda r:(r['step_count'],r['ref']))
        representatives={'FEWER_STEPS':[stable[0]],'LOWER_KNOWN_FEE':[],
                         'LESS_UNCERTAINTY':[min(items,key=_uncertainty)],
                         'NO_CHALLENGE':[min(items,key=lambda r:({'NONE':0,'REQUIRED':1,'UNKNOWN':2}.get(r['challenge'],2),r['step_count'],r['ref']))]}
        money=defaultdict(list)
        for route in items:
            if route['cost']['state']!='KNOWN':continue
            currencies={x['currency'] for x in route['cost']['totals'] if x['currency'] is not None}
            if len(currencies)>1:continue
            currency=next(iter(currencies),'FREE')
            total=sum((Decimal(x['amount']) for x in route['cost']['totals']),Decimal(0))
            if total==0:currency='FREE'
            money[currency].append((total,route['step_count'],route['ref'],route))
        for currency in sorted(money,key=lambda c:(c!='FREE',c)):
            representatives['LOWER_KNOWN_FEE'].append(min(money[currency],key=lambda x:x[:3])[3])
        ordered=[];seen=set()
        priorities=list(dict.fromkeys([*preferences,'FEWER_STEPS','LOWER_KNOWN_FEE','LESS_UNCERTAINTY','NO_CHALLENGE']))
        for dimension in priorities:
            for route in representatives.get(dimension,[]):
                reasons=route.setdefault('selection_reasons',[])
                if dimension not in reasons:reasons.append(dimension)
                if route['ref'] not in seen:ordered.append(route);seen.add(route['ref'])
        ordered.extend(route for route in stable if route['ref'] not in seen)
        queues[(target,classification)]=deque(ordered)
        overview.append({'name':target,'classification':classification,'count':len(items)})
    result=[]
    for classification in sorted({key[1] for key in queues},key=lambda c:(c!='MATCH',c)):
        keys=sorted(key for key in queues if key[1]==classification)
        while any(queues[key] for key in keys):
            for key in keys:
                if queues[key]:result.append(queues[key].popleft())
    return result,overview
