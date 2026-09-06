from journeyplus.agent.recommendation import recommendation_subset


def test_explicit_recommendation_presentation_intent():
    from journeyplus.agent.recommendation import recommendation_requested
    assert recommendation_requested('先推荐最多三条，其他我自己展开浏览')
    assert not recommendation_requested('不用推荐，我要浏览所有路径')
    assert not recommendation_requested('浏览原查询的匹配关系')


def test_recommendation_has_one_primary_keeps_nearby_distinct_and_preserves_exploration():
    routes=[{'ref':str(i),'classification':'MATCH' if i>0 else 'NEARBY'} for i in range(6)]
    selected=recommendation_subset(routes)
    assert [r['ref'] for r in selected]==['1','2','3']
    assert [r['presentation_role'] for r in selected]==['PRIMARY','ALTERNATIVE','ALTERNATIVE']
    assert len(routes)==6 and all('presentation_role' not in r for r in routes)
    selected=recommendation_subset(routes[:2])
    assert len(selected)==1 and selected[0]['presentation_role']=='PRIMARY'
    assert recommendation_subset(routes[:1])[0]['presentation_role']=='NEARBY'


def test_equal_steps_prefers_proven_free_without_guessing_tier_value_or_exchange():
    def route(ref,amount,currency):return {'ref':ref,'classification':'MATCH','step_count':1,'cost':{'state':'KNOWN','is_proven_free':amount==0,'totals':[{'currency':currency,'amount':str(amount)}]}}
    routes=[route('paid',49,'USD'),route('free',0,'USD')]
    result=recommendation_subset(routes)
    assert result[0]['ref']=='free' and '权益价值' in result[0]['recommendation_basis']
    result=recommendation_subset([route('usd',149,'USD'),route('eur',99,'EUR')])
    assert result[0]['ref']=='usd' and '不同币种不作金额高低比较' in result[0]['recommendation_basis']
    assert recommendation_subset(routes,preserve_order=True)[0]['ref']=='paid'
