from copy import deepcopy
import pytest
from journeyplus.agent.harness.contracts import ToolResult
from journeyplus.agent.tools.result_explanation import explain_routes


@pytest.mark.parametrize('result,state', [
    (ToolResult(status='PARTIAL', data={'candidates': []}, coverage={'stopped_reason':'SOURCE_IDENTITY_REQUIRED','search_performed':True,'search_complete':False}), 'MISSING_CONDITIONS'),
    (ToolResult(status='EMPTY', coverage={'stopped_reason':'NO_ACTIVE_SAVED_HOLDINGS','complete':True}), 'NO_ACTIVE_SOURCES'),
    (ToolResult(status='AMBIGUOUS', data={'readiness':{'ready':False},'unresolved_sources':[{'resolution_state':'TIER_REQUIRED','candidates':[{'ref':'tier:a'}]}]}), 'UNRESOLVED_IDENTITY'),
    (ToolResult.failure('UNAVAILABLE','Not available'), 'ERROR'),
    (ToolResult(status='PARTIAL', coverage={'search_complete':False,'total':0}), 'PARTIAL_SEARCH'),
    (ToolResult(status='EMPTY', data={'candidates':[]}, coverage={'search_complete':True,'total':0,'knowledge_complete':False}), 'NO_MATCH_IN_SCOPE'),
    (ToolResult(data={'candidates':[{'ref':'route:a'}]}, coverage={'search_complete':True,'total':1}), 'SEARCH_COMPLETED'),
    (ToolResult(data={'candidates':[]}, coverage={'complete':True}), 'OBSERVATION'),
])
def test_explanation_adds_only_guidance(result,state):
    original=deepcopy(result.model_dump())
    projected=explain_routes(result)
    assert projected.data['result_interpretation']['state']==state
    assert explain_routes(projected)==projected
    assert result.model_dump()==original
    expanded=projected.model_dump()
    del expanded['data']['result_interpretation']
    assert expanded==original


def test_page_end_is_not_no_matches_and_keeps_cursor():
    result=ToolResult(data={'candidates':[]},next_cursor='next',coverage={'search_complete':True,'total':6,'retrieval_complete':False})
    projected=explain_routes(result)
    assert projected.data['result_interpretation']['state']=='SEARCH_COMPLETED'
    assert '尚未全部读取' in projected.data['result_interpretation']['message']
    assert projected.next_cursor=='next'


def test_resolved_subset_does_not_claim_all_sources_searched():
    result=ToolResult(status='PARTIAL',data={'unresolved_sources':[{'code':'CATALOG_GAP'}]},coverage={'search_complete':True,'total':2})
    assert explain_routes(result).data['result_interpretation']['state']=='PARTIAL_SEARCH'
