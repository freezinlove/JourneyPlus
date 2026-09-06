import pytest
from journeyplus.agent.completion import explicit_route_assessment,missing_route_assessment


@pytest.mark.parametrize('text',[
    '我有 A Gold，想看匹配 B Platinum 的路径和费用',
    '假设我有 A Silver，比较匹配 B Gold 和 C Gold 的费用与条件',
    '请帮我找去目标等级的路线',
    'Show matching routes from my Gold status',
    '看看有什么不需要已有会籍的申请机会，不使用保存的会籍',
])
def test_explicit_assessment(text):
    assert explicit_route_assessment(text)
    assert missing_route_assessment(text,[{'tool':'query_activity_materials','status':'OK'}])
    assert not missing_route_assessment(text,[{'tool':'query_membership_routes','status':'PARTIAL'}])


@pytest.mark.parametrize('text',[
    'A Gold 的匹配活动申请费多少？', '比较49和199这两个费用', '今天心情不错',
    '不用查询路径，只问活动申请费', '把“帮我找匹配路径”翻译成英文',
    '换个话题，给我写一首诗',
    '“无需已有会籍的申请机会”是什么意思？',
])
def test_no_forced_pipeline(text):assert not explicit_route_assessment(text)
