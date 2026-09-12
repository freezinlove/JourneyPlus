"""Pure helpers for the retained historical packet-format regression."""
from decimal import Decimal
import json
from pydantic import Field
from journeyplus.contracts import StrictModel


class Amount(StrictModel):
    currency:str|None=None
    role:str
    amount:Decimal


class RouteFact(StrictModel):
    ref:str
    step_count:int
    classification:str
    challenge:str
    eligibility:str
    cost_state:str
    proven_free:bool
    amounts:list[Amount]=Field(default_factory=list)


class ExtractedFacts(StrictModel):
    routes:list[RouteFact]=Field(max_length=60)
    search_complete:bool


def markdown(value,depth=0):
    """Same typed fields/values; headings replace JSON object delimiters."""
    lines=[]
    items=value.items() if isinstance(value,dict) else enumerate(value) if isinstance(value,list) else None
    if items is None:return json.dumps(value,ensure_ascii=False,separators=(',',':'))
    for key,item in items:
        prefix='  '*depth+'- '+json.dumps(str(key),ensure_ascii=False)+': '
        if isinstance(item,(dict,list)) and item:lines.append(prefix.rstrip());lines.append(markdown(item,depth+1))
        else:lines.append(prefix+json.dumps(item,ensure_ascii=False,separators=(',',':')))
    return '\n'.join(lines)


def expected(route):
    return RouteFact(ref=route['ref'],step_count=route['step_count'],classification=route['classification'],challenge=route['challenge'],eligibility=route['eligibility'],cost_state=route['cost']['state'],proven_free=route['cost']['is_proven_free'],amounts=route['cost']['totals'])


def canonical(fact):
    value=fact.model_dump(mode='json');value['amounts']=sorted((a.currency or '',a.role,str(a.amount.normalize())) for a in fact.amounts)
    return value


