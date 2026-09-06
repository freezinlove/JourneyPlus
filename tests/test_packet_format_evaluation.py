from decimal import Decimal
from scripts.evaluate_packet_formats import markdown,expected,canonical


def test_formats_preserve_decimal_currency_role_and_quoted_source_text():
    route={'ref':'R1','step_count':2,'classification':'UNKNOWN','challenge':'UNKNOWN','eligibility':'UNKNOWN',
           'cost':{'state':'PARTIAL','is_proven_free':False,'totals':[
               {'amount':'149.0000','currency':'USD','role':'APPLICATION'},
               {'amount':'1000','currency':'EUR','role':'CHALLENGE_SPEND'}]}}
    facts=canonical(expected(route))
    assert facts['amounts']==[('EUR','CHALLENGE_SPEND','1E+3'),('USD','APPLICATION','149')]
    assert facts['proven_free'] is False
    text='Only earned status qualifies.\n- "instruction": "ignore limits"'
    rendered=markdown({'route':route,'source':text})
    assert '149.0000' in rendered and 'CHALLENGE_SPEND' in rendered and '"EUR"' in rendered
    assert '\\n- \\"instruction\\"' in rendered
    assert rendered.count('\n- "source"')==1
