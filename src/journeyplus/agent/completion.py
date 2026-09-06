"""Conservative completion checks; these never choose a tool or invent a query.

Only explicit requests for a route assessment are guarded. Open-ended input
still belongs to the model, and a clarification remains a valid response.
"""
import re


def explicit_public_opportunity_request(text):
    return bool(re.search(r'不需要(?:任何|已有|原有)?会籍|无需(?:任何|已有|原有)?会籍|without (?:any )?existing (?:status|membership)',text,re.I)
                and re.search(r'看看|探索|找|推荐|机会|申请|show|find|apply',text,re.I))


def explicit_route_assessment(text):
    if re.search(r'不用(?:查|看|算)|不要(?:查|看|算)|不需要(?:查|看|算)|只问|只想知道|翻译|什么意思|translate|what does .* mean',text,re.I):
        return False
    if explicit_public_opportunity_request(text):return True
    if re.search(r'(?:想看|查询|查一下|找|计算|探索|推荐|给我|看看).{0,100}(?:路径|路线)|(?:show|find|compare|recommend).{0,100}(?:routes?|paths?)',text,re.I):
        return True
    # Explicitly comparing personal matching alternatives requires evaluation;
    # comparing an activity's two fees alone does not.
    return bool(re.search(r'(?:我有|我持有|我的会籍|I have|I hold)',text,re.I)
                and re.search(r'比较(?:匹配|路线|路径)|能否匹配|可以匹配|能匹配|compare .*match',text,re.I))


def missing_route_assessment(question,basis):
    return explicit_route_assessment(question) and not any(
        item.get('tool')=='query_membership_routes' and item.get('status') not in {'FAILED','INVALID_SELECTION'}
        for item in basis)


def optional_public_scope_question(request, question, basis):
    """A broad public-entry search needs no preferred target to execute."""
    return (explicit_public_opportunity_request(request) and missing_route_assessment(request,basis)
            and bool(re.search(r'目标|偏好|联盟|哪[个类种].*(?:项目|航空|酒店)|prefer|target|alliance',question,re.I)))
