from journeyplus.agent.narration import narrate,guard_sentence


def test_actual_incremental_sentence_delivery_before_generator_finishes():
    events=[]
    class Provider:
        def stream_text(self,**kwargs):
            yield '申请费为 149 美元。'
            assert events==[('text_delta',{'text':'申请费为 149 美元。'})]
            yield '有效期为 12 个月。'
    answer={'text':'申请费 149 美元，有效期 12 个月。','blocks':[]}
    result=narrate(Provider(),'费用和有效期',answer,{},[],lambda *args:events.append(args))
    assert result['text']=='申请费为 149 美元。有效期为 12 个月。'


def test_unverified_numeric_claim_not_released():
    events=[]
    class Provider:
        def stream_text(self,**kwargs):yield '申请费 999 美元。'
    result=narrate(Provider(),'费用',{'text':'申请费 149 美元。','blocks':[]},{},[],lambda *args:events.append(args))
    assert '999' not in str(events)
    assert result['narration_repaired']


def test_currency_and_amount_cannot_be_swapped_or_invented():
    assert guard_sentence('申请费 149 美元。','USD 149，有效期12个月',{})
    assert not guard_sentence('申请费 149 欧元。','USD 149，有效期12个月',{})
    assert not guard_sentence('申请费 12 美元。','USD 149，有效期12个月',{})


def test_research_does_not_reintroduce_qualification_or_ask_for_preferences():
    events=[]
    class Provider:
        def stream_text(self,**kwargs):
            yield '有 1 例部分可比案例。'
            yield '目前缺少你的证件信息，请你提供'
    result=narrate(Provider(),'查申请经验',{'text':'有 1 例部分可比案例。','blocks':[]},
                   {'current_research_results':[{}]},[],lambda *args:events.append(args))
    assert result['text']=='有 1 例部分可比案例。'
    assert '证件' not in str(events)


def test_unknown_price_can_be_explained_without_claiming_free_or_paid():
    assert guard_sentence('目前还不能确认它是否免费。','费用待核实。',{})
    assert guard_sentence('费用未知不代表免费。','费用待核实。',{})
    assert not guard_sentence('它可以免费申请。','费用待核实。',{})
    assert not guard_sentence('尚未确认费用，所以免费申请。','费用待核实。',{})
    assert not guard_sentence('无法确认是否免费，但你可以免费申请。','费用待核实。',{})
