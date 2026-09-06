"""Presentation-only recommendation limits; exploration caches stay complete."""
from decimal import Decimal
import re


def recommendation_requested(text):
    """Narrow presentation intent for deterministic fallback; never a tool router."""
    if re.search(r'(?:不(?:用|要|必|需)|无需|别)\s*(?:给我|进行)?\s*推荐|do not recommend|no recommendations',text,re.I):return False
    return bool(re.search(r'推荐|首选|精选|\brecommend(?:ation|ations)?\b',text,re.I))


def recommendation_subset(routes,preferences=(),preserve_order=False):
    currencies={amount['currency'] for route in routes if route.get('cost',{}).get('state')=='KNOWN'
                for amount in route['cost'].get('totals',[]) if Decimal(amount['amount'])>0}
    comparable=len(currencies)<=1
    priorities=list(dict.fromkeys([*preferences,'FEWER_STEPS','LOWER_KNOWN_FEE','LESS_UNCERTAINTY']))
    def score(route):
        cost=route.get('cost',{});known=cost.get('state')=='KNOWN'
        free=bool(cost.get('is_proven_free'))
        amount=sum((Decimal(a['amount']) for a in cost.get('totals',[])),Decimal(0)) if known and comparable else Decimal(0)
        metrics={'FEWER_STEPS':(route.get('step_count',0),),
                 'LOWER_KNOWN_FEE':(not free,not known,amount),
                 'LESS_UNCERTAINTY':(len(route.get('unknowns',[]))+int(not known)+int(route.get('eligibility')!='PASS')+int(route.get('challenge')=='UNKNOWN'),)}
        return (route['classification']!='MATCH',*(metrics[p] for p in priorities if p in metrics))
    eligible=[route for route in routes if route['classification']=='MATCH']
    ordered=sorted(eligible or routes,key=(lambda r:r['classification']!='MATCH') if preserve_order else score)[:3]
    primary=False;result=[]
    reason='按本次可比经验资料的保守顺序展示，不代表真实成功率。' if preserve_order else '按'+('、'.join({'FEWER_STEPS':'较少步骤','LOWER_KNOWN_FEE':'较低已知费用','LESS_UNCERTAINTY':'较少待核对项'}[p] for p in priorities))+'依次比较；不比较目标会籍的权益价值。'
    if not comparable:reason+='不同币种不作金额高低比较。'
    for route in ordered:
        role='NEARBY'
        if route['classification']=='MATCH':
            role='ALTERNATIVE' if primary else 'PRIMARY';primary=True
        result.append({**route,'presentation_role':role,'recommendation_basis':reason})
    return result
