from contextlib import nullcontext
from datetime import date,timedelta
import pytest
from journeyplus.agent.services.route_query import RouteQueries
from journeyplus.agent.tools.contracts import RouteRequest,Sources

class Knowledge:
    def read(self):return nullcontext(None)
class Identities:
    def catalog(self,s):return ([1],[],[])
    def resolve(self,s,value,**kw):
        value=value.model_dump(exclude_none=True) if hasattr(value,'model_dump') else value
        name=value.get('program_name','')
        ref=value.get('ref','')
        if name=='unknown':return {'status':'NOT_FOUND','code':'CATALOG_GAP','candidates':[]}
        programme='ana' if name=='ANA' or ref.startswith('tier:ana') else 'lh'
        return {'status':'OK','program_ref':'program:'+programme,'program_name':programme,'tier_ref':ref or None,'tier_name':ref,'ref':ref or 'program:'+programme}
class Data:
    def __init__(self,holdings):self.holdings=holdings
    def route_sources(self,*a):return self.holdings

def holding(tier,expiry=None):
    return {'holding_ref':'holding:'+tier,'program_name':'ANA' if tier.startswith('ana') else '汉莎','tier_name':tier,'tier_ref':'tier:'+tier,'revision':1,'valid_until':expiry}

def query(name='汉莎'):return RouteRequest.model_validate({'sources':{'mode':'saved','saved_program':name}})

def test_filter_uses_one_program_and_preserves_expiry_explanation():
    past=(date.today()-timedelta(days=3)).isoformat()
    service=RouteQueries(Knowledge(),Data([holding('senator'),holding('old',past),holding('ana-gold')]),Identities())
    result=service.prepare(query())
    assert [r['tier_ref'] for r in result['sources']]==['tier:senator']
    assert len(result['source_selection']['excluded_holdings'])==1
    assert result['readiness']['ready']

def test_multiple_effective_tiers_are_ambiguous():
    service=RouteQueries(Knowledge(),Data([holding('senator'),holding('hon')]),Identities())
    result=service.evaluate(query())['error']
    assert result.status=='AMBIGUOUS'
    assert result.coverage['search_performed'] is False

def test_no_matching_saved_program_is_empty_not_other_holdings():
    service=RouteQueries(Knowledge(),Data([holding('ana-gold')]),Identities())
    result=service.evaluate(query())['error']
    assert result.coverage['stopped_reason']=='NO_ACTIVE_SAVED_HOLDINGS'
    assert result.data['source_selection']['saved_program']=='汉莎'

@pytest.mark.parametrize('mode',['none','explicit'])
def test_filter_requires_saved_mode(mode):
    with pytest.raises(ValueError):Sources.model_validate({'mode':mode,'saved_program':'汉莎'})
