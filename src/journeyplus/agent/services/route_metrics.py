"""Comparison facts only. The model chooses recommendations and display order."""
from decimal import Decimal


def metrics(routes):
    items=[];currencies={}
    for route in routes:
        cost=route.get('cost',{})
        item={'ref':route['ref'],'steps':route.get('step_count'),'cost':cost,
              'challenge':route.get('challenge','UNKNOWN'),'eligibility':route.get('eligibility','UNKNOWN'),
              'classification':route.get('classification','UNKNOWN')}
        items.append(item)
        totals=cost.get('totals',[])
        if cost.get('state')=='KNOWN' and len(totals)==1 and totals[0].get('currency'):
            value=totals[0]
            currencies.setdefault(value['currency'],[]).append((Decimal(str(value['amount'])),route['ref']))
    minima=[]
    for currency,values in currencies.items():
        amount=min(value for value,_ in values)
        minima.append({'currency':currency,'known_amount':str(amount),'route_refs':[ref for value,ref in values if value==amount]})
    return {'items':items,'proven_free_route_refs':[route['ref'] for route in routes if route.get('cost',{}).get('is_proven_free')],'minimum_known_cost_by_currency':minima,'scope':'supplied_routes_only',
            'limitations':['No currency conversion. Unknown fees are not zero. Cost alone does not prove eligibility or recommend a route.']}
