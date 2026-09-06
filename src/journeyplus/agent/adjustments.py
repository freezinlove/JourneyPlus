"""Minimal proposed changes derived only from evaluated near-miss routes."""
from decimal import Decimal
import re


def adjustment_requested(text):
    return bool(re.search(r'最小.{0,8}调整|最小.{0,8}放宽|minimum.{0,12}adjust',text,re.I))


def preserve_adjustment_budget(query, text, prior_query=None):
    """Preserve an unambiguous, explicit original cap during adjustment evaluation.

    This is a narrow guard, not a natural-language parser. Ambiguous currencies,
    multiple caps and indirect/quoted statements are left to clarification.
    """
    if not adjustment_requested(text):
        return query
    clauses=re.split(r'[。！？\n；;]',text)
    matches=[]
    for clause in clauses:
        if re.search(r'[“”「」"\']|不是|并非|之前|以前|原来|他说|她说|例如|比如',clause):
            continue
        matches.extend(re.findall(r'预算\s*(?:最多|不超过|上限(?:是|为)?)\s*([0-9]+(?:\.[0-9]{1,2})?)\s*(美元|美金|欧元|人民币|USD|EUR|CNY)(?![A-Za-z])',clause,re.I))
    if len(matches)!=1:
        return query
    amount,currency=matches[0]
    currencies={'美元':'USD','美金':'USD','欧元':'EUR','人民币':'CNY'}
    result={**query,'max_amount':amount,'currency':currencies.get(currency,currency.upper())}
    # "Only adjust the budget" is not an instruction to reject all challenges.
    # Preserve an existing explicit constraint, but do not accept a new one that
    # appeared only in the model's arguments for this narrow budget request.
    prior_query=prior_query or {}
    if result.get('allow_challenge') is not None and prior_query.get('allow_challenge') is None and not re.search(r'挑战|住宿|飞行|challenge|stay|flight',text,re.I):
        result['allow_challenge']=None
    if result.get('free_only') and not prior_query.get('free_only') and not re.search(r'免费|free',text,re.I):
        result['free_only']=False
    return result


def minimal_adjustment(state,refs):
    if state.get('adjustment_rejected'):return None
    query=state.get('query',{});candidates=[]
    for ref in state.get('current_route_refs',[]):
        route=state.get('routes',{}).get(ref,{})
        if route.get('classification')!='NEARBY' or len(route.get('violations',[]))!=1:continue
        field=route['violations'][0];value=None
        if re.search(r'预算|金额',state.get('current_question','')) and field!='max_amount':continue
        if field=='max_amount' and route['cost']['state']=='KNOWN':
            totals=route['cost']['totals']
            if any(p['currency'] not in {None,query.get('currency')} for p in totals):continue
            value=format(sum((Decimal(p['amount']) for p in totals),Decimal(0)).normalize(),'f')
        elif field=='free_only':value=False
        elif field=='allow_challenge':value=True
        else:continue
        candidates.append((field,Decimal(value) if field=='max_amount' else Decimal(0),ref,value))
    if not candidates:return None
    field,_,ref,value=min(candidates)
    return {'kind':'QUERY_ADJUST','changes':{field:value},'reason':'最小条件调整','support_refs':refs.encode([ref])}


def confirmation_question(text):
    return bool(re.search(r'确认(?:是否)?(?:接受|保存|创建|修改)|接受此调整|是否同意.{0,8}(?:创建|保存|修改|调整)',text))


def single_clarification(text):
    """Keep the first complete question; never shorten a business fact packet."""
    questions=list(re.finditer(r'[?？]',text))
    return text[:questions[0].end()] if len(questions)>1 else text
