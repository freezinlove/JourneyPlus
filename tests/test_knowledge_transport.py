import pytest
from pydantic import ValidationError
from journeyplus.knowledge.transport import ModelDecisionPacket,PresentationData,ServerRouteResult
from journeyplus.knowledge.packets import project_model_packet
from journeyplus.knowledge.references import ReferenceMap


def test_full_search_and_diagnostics_never_become_disclosed_references():
    class InternalOnly:
        def __deepcopy__(self,memo):raise AssertionError('Internal object was copied')
    raw={'status':'PARTIAL','server_routes':InternalOnly(),'snapshot':InternalOnly(),
         'data':{'reason_counts':{'硬条件失败':2},'server_cache':InternalOnly(),'activities':[{'ref':'1234567890abcdef','name':'Example'}]}}
    refs=ReferenceMap({});packet=refs.encode_packet(raw)
    assert packet['data']['reason_counts']=={'硬条件失败':2}
    assert set(packet)=={'status','data'} and len(refs.entries)==1


def test_separate_contracts_reject_cross_boundary_fields_and_orm_objects():
    with pytest.raises(ValidationError):ModelDecisionPacket.model_validate({'status':'OK','server_routes':{}})
    with pytest.raises(ValidationError):PresentationData.model_validate({'activities':[],'snapshot':{}})
    with pytest.raises(ValueError):project_model_packet({'status':'OK','data':{'activities':[object()]}})
    with pytest.raises(ValueError):project_model_packet({'data':{}})


def test_server_and_presentation_require_complete_step_references():
    with pytest.raises(ValidationError):ServerRouteResult.model_validate({'status':'OK','snapshot':{},'server_routes':{'r':{'ref':'r','step_refs':['missing']}},'server_steps':{}})
    with pytest.raises(ValidationError):PresentationData.model_validate({'routes':[{'ref':'r','step_refs':['missing']}],'steps':{}})
    assert PresentationData.model_validate({'routes':[{'ref':'r','step_refs':['s']}],'steps':{'s':{'ref':'s'}}})


def test_identifier_arguments_cannot_address_an_undisclosed_cached_object():
    state={'routes':{'1234567890abcdef':{'ref':'1234567890abcdef'}}}
    refs=ReferenceMap(state)
    with pytest.raises(ValueError):refs.require_disclosed({'route_refs':['1234567890abcdef']})
    with pytest.raises(ValueError):refs.require_disclosed({'query':{'starting_tier_ids':['K9999']}})
    short=refs.encode('1234567890abcdef')
    refs.require_disclosed({'route_refs':[short]})
    refs.require_disclosed({'selector':{'text':'Example'},'query':{'max_amount':100,'currency':'USD'}})
