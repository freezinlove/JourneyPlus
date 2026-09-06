from uuid import uuid4
import pytest

from journeyplus.knowledge.routes import RouteService,RouteQuery,conditions_result


def step(amount='200',currency='EUR',unknown=False,challenge='NONE'):
    return {'fees':[{'currency':currency,'role':'APPLICATION','amount':amount}],
            'fee_unknown':unknown,'challenge':challenge,'eligibility':'PASS','availability':'AVAILABLE',
            'from':'A','to':'B','conditional_items':[],'alternative_items':[],'material_caveats':[],'fact_refs':[]}


@pytest.mark.parametrize('steps,query,classification,violation',[
    ([step()],{'max_amount':100,'currency':'EUR'},'NEARBY','max_amount'),
    ([step(unknown=True)],{'max_amount':100,'currency':'EUR'},'EXCLUDED','max_amount'),
    ([step('90'),step('10','USD')],{'max_amount':100,'currency':'EUR'},'UNKNOWN',None),
    ([step('120'),step('10','USD',unknown=True)],{'max_amount':100,'currency':'EUR'},'EXCLUDED','max_amount'),
    ([step('0',unknown=True)],{'free_only':True},'UNKNOWN',None),
    ([step('0',challenge='UNKNOWN')],{'allow_challenge':False},'UNKNOWN',None),
    ([step(challenge='REQUIRED')],{'max_amount':100,'currency':'EUR','allow_challenge':False},'EXCLUDED','allow_challenge'),
])
def test_formal_budget_and_challenge_gold_cases(steps,query,classification,violation):
    refs=[str(i) for i in range(len(steps))]
    r=RouteService(None)._summarize(refs,dict(zip(refs,steps)),RouteQuery(**query))
    assert r['classification']==classification
    if violation:assert violation in r['violations']
    if any(s['fee_unknown'] for s in steps):assert not r['cost']['is_proven_free']
    if len({s['fees'][0]['currency'] for s in steps})>1:assert len(r['cost']['totals'])==2


def test_reused_condition_id_cannot_silently_erase_known_failure():
    evidence=str(uuid4())
    def condition(value,**extra):
        return {'condition_id':'source','topic':'SOURCE_ACQUISITION','known_state':'KNOWN','operator':'EQ',
                'value':value,'raw_text':value,'evidence_ids':[evidence],**extra}
    groups=[{'items':[condition('EARNED')]},{'items':[condition('MATCHED')]}]
    result,checks=conditions_result(groups,{'SOURCE_ACQUISITION':'MATCHED'})
    assert result=='FAIL' and len(checks)==2
    groups[1]['items'][0]['supersedes_ids']=['source']
    result,checks=conditions_result(groups,{'SOURCE_ACQUISITION':'MATCHED'})
    assert result=='PASS' and len(checks)==1
