import pytest

from journeyplus.agent.adjustments import preserve_adjustment_budget


@pytest.mark.parametrize('query',[{}, {'max_amount':'149','currency':'USD'}])
def test_original_explicit_cap_survives_model_omission_or_relaxation(query):
    result=preserve_adjustment_budget(query,'预算最多 100 美元。如果只差预算，请给一个最小金额调整。')
    assert result=={'max_amount':'100','currency':'USD'}
    assert query.get('max_amount')!='100'


@pytest.mark.parametrize('text',[
    '预算最多100元，请给最小调整。',
    '之前预算最多100美元，现在预算上限为200美元，请给最小调整。',
    '预算最多100美元，预算上限200欧元，请给最小调整。',
    '他说“预算最多100美元”，请给最小调整。',
    '预算不是最多100美元，请给最小调整。',
    '例如预算最多100美元，请解释最小调整。',
    '预算最多100美元，列出方案。',
])
def test_guard_does_not_guess_ambiguous_or_unrelated_intent(text):
    query={'target_tier_id':'target'}
    assert preserve_adjustment_budget(query,text)==query


def test_budget_adjustment_does_not_add_unrequested_free_or_no_challenge_constraints():
    text='预算最多100美元，请给一个最小金额调整。'
    result=preserve_adjustment_budget({'allow_challenge':False,'free_only':True},text)
    assert result['allow_challenge'] is None and result['free_only'] is False
    assert preserve_adjustment_budget({'allow_challenge':False},text,{'allow_challenge':False})['allow_challenge'] is False
    assert preserve_adjustment_budget({'allow_challenge':False},text+'但不接受挑战。')['allow_challenge'] is False
