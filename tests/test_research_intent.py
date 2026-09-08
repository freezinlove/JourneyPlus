from journeyplus.agent.research_intent import explicit_research_request


def test_capability_notice_only_for_explicit_request():
    assert explicit_research_request('帮我查一下 StatusMatcher 上 Royal Jordanian 的申请经验')
    assert explicit_research_request('这些方案哪个更稳？')
    assert not explicit_research_request('不要查 StatusMatcher，只看官方费用')
    assert not explicit_research_request('润色这句话：调查申请经验很重要。')
    assert not explicit_research_request('讲个生活经验的笑话')


def test_long_named_step_does_not_hide_disabled_capability():
    description='某个很长的会员项目名称及其完整等级名称'*8
    assert explicit_research_request('请先调查 '+description+' 这一步的近期申请经验，不用规划行程')
    assert not explicit_research_request('请翻译：调查 '+description+' 的申请经验')


def test_repeat_reuses_cache_unless_fresh_source_is_requested():
    from journeyplus.agent.research_intent import explicit_research_refresh
    assert not explicit_research_refresh('再查一次这条路径的 StatusMatcher 申请经验。')
    assert explicit_research_refresh('不要缓存，重新联网查最新报告')
