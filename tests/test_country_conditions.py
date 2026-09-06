from uuid import uuid4
from journeyplus.knowledge.routes import conditions_result


def evaluate(actual,expected,effect='REQUIRE'):
    group={'items':[{'condition_id':'region','topic':'RESIDENCY','operator':'IN','value':expected,
        'known_state':'KNOWN','raw_text':'regional eligibility','effect':effect,'evidence_ids':[str(uuid4())]}]}
    return conditions_result([group],{'RESIDENCY':actual})[0]


def test_country_aliases_do_not_become_false_eligibility_failures():
    for actual in ['CA','Canada','加拿大',' ca ']:assert evaluate(actual,['Canada'])=='PASS'
    assert evaluate('Brazil',['巴西'],'EXCLUDE')=='FAIL'
    assert evaluate('Canada',['Greece'])=='FAIL'


def test_ambiguous_region_names_remain_unknown_including_exclusions():
    assert evaluate('Korea',['South Korea'])=='UNKNOWN'
    assert evaluate('England',['UK'])=='UNKNOWN'
    assert evaluate('Canada',['Americas'])=='UNKNOWN'
    assert evaluate('Canada',['Greece','unresolved region'],'EXCLUDE')=='UNKNOWN'
