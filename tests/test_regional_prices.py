from journeyplus.knowledge.regional_prices import regional_fee_rows,region_scope_matches

TABLE='''| **Country/Region** | **Status Tier** | **Application Fee** Listed in USD |
| Argentina, Brazil | Silver | USD 99 |
| | Gold | USD 299 |
| | Platinum | USD 399 Not Available for Brazil |'''


def condition(value,effect='REQUIRE'):
    return {'topic':'RESIDENCY','known_state':'KNOWN','operator':'IN','value':value,'effect':effect}


def test_blank_region_cell_inherits_only_within_explicit_table():
    rows=regional_fee_rows(TABLE)
    assert len(rows)==3 and rows[1]['region']=='Argentina, Brazil'
    assert rows[2]['qualifier']=='Not Available for Brazil'
    assert regional_fee_rows('| | Gold | USD 299 |')==[]
    assert len(regional_fee_rows(TABLE+'\nUnrelated section\n| | Diamond | USD 1 |'))==3


def test_region_and_exclusion_cannot_disappear_when_grounding():
    row=regional_fee_rows(TABLE)[2]
    option={'conditions':{'items':[condition(['Argentina','Brazil'])]}}
    assert not region_scope_matches(row,option,{})
    price={'conditions':{'items':[condition(['Brazil'],'EXCLUDE')]}}
    assert region_scope_matches(row,option,price)
    assert not region_scope_matches(row,{'conditions':{'items':[condition(['Greece'])]}},price)
    assert not region_scope_matches(row,{},price)
