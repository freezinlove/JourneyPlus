from journeyplus.knowledge.token_budget import InputTokenBudget


def metric(size,tokens,system=100):
    return {'user_prompt_bytes':size,'system_prompt_bytes':system,'schema_bytes':200,'usage':{'prompt_tokens':tokens}}


def test_incremental_calibration_keeps_system_tokens_out_of_tool_estimate():
    state={};b=InputTokenBudget(state,'configured-model')
    b.observe(metric(284,3853));b.observe(metric(19822,9016))
    assert b.calibration['samples']==1
    assert b.byte_limit(False,21000)==21000
    assert b.describe(18000,False)['estimated_tool_tokens']==6000
    assert not b.describe(18000,False)['includes_system_and_schema']


def test_higher_observed_density_reduces_next_budget_and_survives_reload():
    state={};b=InputTokenBudget(state,'model')
    b.observe(metric(100,1000));b.observe(metric(10100,7000))
    assert b.byte_limit(False,21000)<10000
    restored=InputTokenBudget(state,'model')
    assert restored.byte_limit(True,15000)==b.byte_limit(True,15000)
    changed=InputTokenBudget(state,'different-model')
    assert changed.calibration['samples']==0


def test_missing_usage_or_changed_schema_is_not_fabricated_as_observation():
    b=InputTokenBudget({},'model');b.observe(None);b.observe({'usage':None})
    b.observe(metric(100,1000));b.observe(metric(10100,7000,system=101))
    assert b.calibration['samples']==0
