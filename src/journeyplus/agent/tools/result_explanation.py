"""Add factual reading guidance to model observations without removing data."""


def explain_routes(result):
    result = result.model_copy(deep=True)
    data, coverage = result.data, result.coverage
    reason = coverage.get('stopped_reason')
    readiness = data.get('readiness') or {}
    if reason == 'SOURCE_IDENTITY_REQUIRED':
        state = 'MISSING_CONDITIONS'
        message = '缺少来源会籍，路径查询未完成；空列表不能说明没有匹配路径。search_performed 仅表示进入查询服务，不表示完成了有效路径搜索。'
    elif reason == 'NO_ACTIVE_SAVED_HOLDINGS':
        state = 'NO_ACTIVE_SOURCES'
        message = '本次没有可用的有效已保存会籍，未执行路径搜索；不能据此判断该项目是否存在匹配机会。排除原因见 source_selection。'
    elif readiness.get('ready') is False:
        state = 'UNRESOLVED_IDENTITY'
        message = '查询身份尚未确定，未完成路径搜索。readiness.issues 指向具体歧义或缺失项，身份候选见 resolved_target / unresolved_sources；空路径不等于无匹配机会。'
        if any(item.get('resolution_state') == 'TIER_REQUIRED' for item in data.get('unresolved_sources', [])):
            message += '来源会籍等级未确定，不同等级可能对应不同路径；候选等级不代表用户持有。'
    elif result.error:
        state = 'ERROR'
        message = '本次操作未成功完成，原因见 error；不能把失败或不可用解释为没有匹配路径。'
    elif 'search_complete' in coverage:
        if not coverage['search_complete'] or data.get('unresolved_sources'):
            state = 'PARTIAL_SEARCH'
            message = '本次搜索存在未完成范围或未解析来源，原因见 coverage 与 unresolved_sources；已返回路径仅代表已完成部分。'
        elif coverage.get('total') == 0 and not data.get('candidates'):
            state = 'NO_MATCH_IN_SCOPE'
            message = '已完成本次已发布规则范围内的路径搜索，没有符合本次条件的路径；不代表未收录渠道也没有机会。'
        else:
            state = 'SEARCH_COMPLETED'
            message = '已完成本次已发布规则范围内的路径搜索。路径符合映射筛选不等于个人申请资格已核验；知识库完整性与本次搜索完成是不同概念。'
        if result.next_cursor or coverage.get('retrieval_complete') is False:
            message += '当前结果尚未全部读取，分页信息和 next_cursor 保留。'
    else:
        # Inspect/compare do not perform a new search. Do not infer search status.
        state = 'OBSERVATION'
        message = '本次返回所选对象的资料；不能据此推断执行了新的全范围路径搜索。结果限制见 coverage。'
    data['result_interpretation'] = {'state': state, 'message': message}
    return result
