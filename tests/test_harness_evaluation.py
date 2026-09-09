"""The existing holdout stays frozen; prose and cross-turn ids cannot pass tools."""
import hashlib,json
from pathlib import Path
from journeyplus.agent.evaluation import assess_case
from journeyplus.agent.harness.contracts import ModelMessage,Part


def test_original_32_cases_and_eight_holdouts_are_unchanged():
    cases=json.loads(Path('tests/fixtures/agent_harness/cases.json').read_text())['cases']
    assert len(cases)==len({case['id'] for case in cases})==32
    held=[case for case in cases if case['split']=='holdout']
    assert len(held)==8
    encoded=json.dumps(held,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(encoded).hexdigest()=='c7c9e97c8fc150a97416b8d8bf513b59aecafd9ea85776a24f1bd2ade4467c55'


def test_prose_or_different_capability_cannot_pass_required_route_read():
    messages=[ModelMessage(role='assistant',content=[Part(type='text',text='已查过路径')])]
    assert assess_case({'tool':'routes.evaluate'},messages,False)==['MISSING_EXPECTED_CAPABILITY']
    messages.extend([
        ModelMessage(role='assistant',metadata={'turn_id':'one'},content=[Part(type='tool_call',call_id='same',name='routes.evaluate',arguments={})]),
        ModelMessage(role='assistant',metadata={'turn_id':'two'},content=[Part(type='tool_call',call_id='same',name='activity.read',arguments={})]),
        ModelMessage(role='tool',metadata={'turn_id':'two'},content=[Part(type='tool_result',call_id='same',result={'status':'OK','data':{}})])])
    assert assess_case({'tool':'routes.evaluate'},messages,False)==['MISSING_EXPECTED_CAPABILITY']
    assert assess_case({'tool':'activity.read'},messages,False)==[]


def test_write_assertions_require_ledger_and_actual_success_receipt():
    assert assess_case({'no_user_write':True},[],True)==['UNAUTHORIZED_USER_WRITE']
    assert assess_case({'authorized_write':True},[],False)==['MISSING_AUTHORIZED_RECEIPT']


def test_query_constraints_and_each_turn_delivery_are_checked_separately():
    messages=[ModelMessage(role='user',content=[Part(type='text',text='hotels only')]),
        ModelMessage(role='assistant',content=[Part(type='tool_call',call_id='a',name='routes.evaluate',arguments={'operation':'search'})]),
        ModelMessage(role='tool',content=[Part(type='tool_result',call_id='a',result={'status':'OK','data':{'effective_query':{'category':None}}})]),
        ModelMessage(role='user',content=[Part(type='text',text='show again')]),
        ModelMessage(role='assistant',content=[Part(type='tool_call',call_id='b',name='display.present',arguments={})]),
        ModelMessage(role='tool',content=[Part(type='tool_result',call_id='b',result={'status':'OK','data':{'blocks':[{'columns':['cost']}]}})])]
    failures=assess_case({'query_fields':{'/category':'HOTEL'},'per_turn':{'0':{'tool':'display.present'},'1':{'presentation_columns':['conditions']}}},messages,False)
    assert failures==['QUERY_FIELD_MISMATCH:/category','TURN_0:MISSING_EXPECTED_CAPABILITY','TURN_1:PRESENTATION_COLUMNS_MISSING']
