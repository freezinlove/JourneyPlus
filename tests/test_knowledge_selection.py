from journeyplus.knowledge.selection import order_candidates


def candidate(ref,steps,amount,currency='USD',known=True):
    return {'ref':ref,'to':'Target','classification':'MATCH','step_count':steps,
            'cost':{'state':'KNOWN' if known else 'UNKNOWN','totals':[{'currency':currency,'amount':str(amount)}] if known else []},
            'unknowns':[],'needs_inspection':not known,'material_caveats':[],
            'challenge':'NONE','eligibility':'PASS'}


def test_shortlist_keeps_cheaper_and_fewer_step_alternatives():
    items=[candidate('fast',1,300),candidate('cheap',2,50),candidate('unknown',1,0,known=False)]
    ordered,_=order_candidates(items)
    assert [r['ref'] for r in ordered[:2]]==['fast','cheap']
    assert {r['ref'] for r in ordered}=={'fast','cheap','unknown'}
    preferred,_=order_candidates(items,['LOWER_KNOWN_FEE'])
    assert preferred[0]['ref']=='cheap'


def test_fee_representatives_do_not_compare_currencies_or_guess_unknown_zero():
    items=[candidate('usd',1,99),candidate('eur',1,200,'EUR'),candidate('unknown',1,0,known=False)]
    ordered,_=order_candidates(items,['LOWER_KNOWN_FEE'])
    assert {r['ref'] for r in ordered[:2]}=={'usd','eur'}
    assert 'LOWER_KNOWN_FEE' not in items[-1].get('selection_reasons',[])
    items.append(candidate('free',2,0,'USD'))
    ordered,_=order_candidates(items,['LOWER_KNOWN_FEE'])
    assert ordered[0]['ref']=='free'


def test_nearby_cannot_displace_matches_in_other_target_groups():
    nearby={**candidate('nearby',1,0),'to':'A target','classification':'NEARBY'}
    first={**candidate('match1',1,149),'to':'Z target'}
    second={**candidate('match2',2,99),'to':'Z target'}
    ordered,_=order_candidates([nearby,first,second])
    assert [r['ref'] for r in ordered]==['match1','match2','nearby']
