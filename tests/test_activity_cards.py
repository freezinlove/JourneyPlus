from journeyplus.knowledge.cards import activity_card


def test_card_never_shows_an_unscoped_minimum_and_retains_unknown_challenge():
    detail={'version_ref':'v','kind':'STATUS_MATCH','facts':{'lifecycle':{'known_state':'KNOWN','value':'OPEN'}},'options':[
        {'label':'Airline','challenge':{'known_state':'UNKNOWN'},'mappings':[{'target_tier_id':'gold','to_tier':'Gold'},{'target_tier_id':'silver','to_tier':'Silver'}],
         'prices':[{'ref':'gold-price','target_tier_id':'gold','known_state':'KNOWN','amount':'149.0000','currency':'USD','availability':'AVAILABLE','fee_role':'APPLICATION'},
                   {'ref':'silver-price','target_tier_id':'silver','known_state':'KNOWN','amount':'49.0000','currency':'USD','availability':'UNKNOWN','combination':'CONDITIONAL','fee_role':'APPLICATION'}]}]}
    card=activity_card(detail)
    assert card['fees'][0]['label']=='Airline · Gold' and card['fees'][0]['value']=='USD 149'
    assert card['fees'][1]['value']=='USD 49' and card['fees'][1]['caveats']==['适用性待核实','附适用条件']
    assert card['challenge']=='UNKNOWN' and card['lifecycle']=='OPEN'
    assert 'minimum' not in card and 'total' not in card


def test_no_prices_is_not_free_and_other_remains_a_card():
    card=activity_card({'version_ref':'v','kind':'OTHER','facts':{},'options':[]})
    assert card['kind']=='OTHER' and card['fees']==[] and '不能据此推断免费' in card['fee_note']
