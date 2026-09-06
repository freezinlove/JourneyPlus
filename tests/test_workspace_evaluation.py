import json
import hashlib
from pathlib import Path
from scripts.evaluate_workspace import assess


def test_evaluation_has_separate_holdout_and_required_layers():
    cases=json.loads(Path('tests/fixtures/workspace_evaluation/tasks.json').read_text())['cases']
    assert 30<=len(cases)<=50 and len({c['id'] for c in cases})==len(cases)
    assert sum(c['split']=='holdout' for c in cases)>=10
    assert {'chat','facts','routes','comparison','research','confirmation','followup'}<={c['category'] for c in cases}


def test_holdout_is_frozen_and_previously_debugged_cases_are_not_holdout():
    fixture=json.loads(Path('tests/fixtures/workspace_evaluation/tasks.json').read_text())
    held=[c for c in fixture['cases'] if c['split']=='holdout']
    digest=hashlib.sha256(json.dumps(held,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert digest==fixture['holdout_policy']['sha256']
    assert all(not c.get('previous_split') for c in held)


def test_evaluator_rejects_paid_or_unknown_challenge_formal_match():
    case={'expect':{'matches_must_be_free':True,'matches_require_no_challenge':True,'max_match_amount':{'amount':'100','currency':'USD'}}}
    answer={'blocks':[{'type':'route_graph','payload':{'routes':[{'classification':'MATCH','challenge':'UNKNOWN','cost':{'is_proven_free':False,'totals':[{'amount':'149','currency':'USD'}]}}]}}]}
    assert set(assess(case,{},[answer]))=={'PAID_MATCH_FOR_FREE_QUERY','OVER_BUDGET_MATCH','UNPROVEN_NO_CHALLENGE_MATCH'}


def test_evaluator_does_not_count_prose_as_a_verified_research_gate():
    case={'expect':{'research_must_be_disabled':True}}
    assert assess(case,{},[{'text':'调查已关闭'}])==['MISSING_EXPLICIT_RESEARCH_GATE']
    assert assess(case,{},[{'basis':[{'tool':'research_statusmatcher','status':'DISABLED'}]}])==[]


def test_activity_read_alone_cannot_pass_a_route_task():
    assert assess({'expect':{'route_read':True}},{},[{'basis':[{'tool':'query_activity_materials'}]}])==['MISSING_ROUTE_EVALUATION']
