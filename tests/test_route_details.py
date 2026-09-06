from copy import deepcopy
from uuid import uuid4
import pytest
from journeyplus.product.knowledge_api import route_activity_detail


def test_route_detail_preserves_exact_option_mapping_and_conditional_prices():
    source={'options':[{'ref':'other','mappings':[],'prices':[]},
                       {'ref':'chosen','mappings':[{'ref':'gold'},{'ref':'silver'}],
                        'prices':[{'ref':'gold-price'},{'ref':'silver-price'},{'ref':'conditional'}]}]}
    class Reader:
        def detail(self,*args):return deepcopy(source)
    step={'activity_ref':str(uuid4()),'version_ref':str(uuid4()),'option_ref':'chosen','mapping_ref':'gold',
          'fees':[{'ref':'gold-price'}],'conditional_items':[{'ref':'conditional'}],'alternative_items':[]}
    result=route_activity_detail(Reader(),step)
    assert len(result['options'])==1
    assert result['options'][0]['mappings']==[{'ref':'gold'}]
    assert result['options'][0]['prices']==[{'ref':'gold-price'},{'ref':'conditional'}]
    assert len(source['options'])==2
    step['mapping_ref']='different-version'
    with pytest.raises(LookupError):route_activity_detail(Reader(),step)
