"""Bounded natural narration of server-verified facts, released a sentence at a time."""
import json
import re

PROMPT='''你是 JourneyPlus 会籍顾问。用自然中文直接回答用户当前的问题，像正常交谈，不列标题、不播报字段、不复述整张卡片。不超过三小段。只依据 verified_brief 的事实，details 仅用于解释其中资格条件，不得从前轮回答补充新事实。金额、期限、资格必须忠于材料；未知不说免费或符合，部分费用不说总费用。用户问待核实事项就具体说明缺哪项用户信息/来源事实。用户明确不限就不要再建议填写偏好。资料不足明确当前库未核实，不说官方没公布。资格尚未核对不等于缺少资格规则；卡片已有具体条件时不能声称没有条件细节。正文用关键结论和限制，卡片已有完整结构。没有来源支持不作成功概率判断。不要输出 Markdown 标题、代码、JSON、内部引用，不能自造 URL。证件签发国家不等于国籍或居住地，不得互换。经验问题只解释经验调查发现，不重复官方资格条件，也不要追问用户的等级或证件。部分可比案例必须明确说部分可比，不能省略成可比。普通数字按提供形式写，禁止换算货币。国家名单只概括为允许的证件签发国家，不要举例国家；完整名单交给卡片，用户询问具体国家时才核对。明确区分：证件、参与历史是需要用户确认的信息；申请截止时间、时区、挑战规则是需要继续查来源的信息，不能要求用户补齐官方资料。不要在结尾习惯性追问偏好或邀请用户选想核实的项。无结果时必须说明 verified_brief 中实际查询的起点和目标，不能泛称该起点没有路径，也不能将间接路径说成仅直接匹配。候选总数和本页展示数是两个不同数量，不得把本页数量说成搜索总数。已有浏览按钮必须说点击该按钮，不能改成要求发消息或告诉你想看哪条。'''


CHAT_PROMPT='你是 JourneyPlus 软件中的 AI 助手，可以帮助查询航空和酒店会籍匹配活动、路径、费用和申请经验。自然简短地回应当前话题，一两句话即可。你没有人类生活、日程或客户预约，不要编造自己刚做了工作。用户换话题时直接聊新话题，不提旧任务，不推销能力，不邀请继续以前的查询。'


def chat(provider,question,emit):
    parts=[]
    for part in provider.stream_text(system_prompt=CHAT_PROMPT,user_prompt=question):
        parts.append(part);emit('text_delta',{'text':part})
    return ''.join(parts)


def ready_for_narration(state,basis,question):
    from journeyplus.agent.completion import explicit_route_assessment
    from journeyplus.agent.adjustments import adjustment_requested
    action_text=re.sub(r'(?:不|不要|不用|无需|先别)保存会籍','',question)
    if adjustment_requested(question) or re.search(r'保存|更新会籍|等待|监控|提醒',action_text):return False
    if re.search(r'statusmatcher|经验|成功率|调查|案例',question,re.I):
        return any(b['tool']=='research_statusmatcher' for b in basis)
    if state.get('current_route_coverage') is not None:return True
    if explicit_route_assessment(question):return False
    return bool(state.get('current_activity_refs') and any(m.get('data',{}).get('facts') for m in state.get('materials',[])[-1:]))


def concise_details(state,answer,question=""):
    route_ids=[r for b in answer['blocks'] for r in b.get('payload',{}).get('routes',[])]
    steps=state.get('steps',{})
    if state.get('focused_step_refs'):
        return compact_checks([{'from':steps[r].get('from'),'to':steps[r].get('to'),'checks':steps[r].get('constraint_checks',[])} for r in state['focused_step_refs'] if r in steps],question)
    selected={ref:steps[ref] for r in route_ids for ref in r.get('step_refs',[]) if ref in steps}
    # Payload references can be encoded, while state keys are raw; use current raw selection.
    if not selected:
        selected={ref:steps[ref] for rid in state.get('current_route_refs',[])[:3] for ref in state.get('routes',{}).get(rid,{}).get('step_refs',[]) if ref in steps}
    return compact_checks([{'from':s.get('from'),'to':s.get('to'),'checks':s.get('constraint_checks',[])} for s in selected.values()][:6],question)


def compact_checks(details,question):
    from copy import deepcopy
    details=deepcopy(details)
    if not re.search(r'哪些国家|国家名单|哪些地区|完整名单|which countries',question,re.I):
        for step in details:
            for check in step.get('checks',[]):
                reason=check.get('reason','')
                if re.search(r'government issued identity.*following countries',reason,re.I):
                    check['reason']='需要持有活动允许国家签发的政府身份证件；完整国家名单见步骤详情。'
    for step in details:
        step['checks']=[{key:check[key] for key in ('topic','result','reason','actual') if check.get(key) is not None} for check in step.get('checks',[])]
        step['check_count']=len(step['checks'])
        step['source_gap_count']=sum(c.get('topic')=='APPLICATION_WINDOW' for c in step['checks'])
        step['user_information_count']=step['check_count']-step['source_gap_count']
    return details


def guard_sentence(sentence,brief,state):
    from journeyplus.agent.answer_grounding import route_text_issues
    # Currency/number inventions are rejected before they reach a stream subscriber.
    from decimal import Decimal
    numeric=lambda text:{Decimal(n) for n in re.findall(r'\d+(?:\.\d+)?',text)}
    if not numeric(sentence)<=numeric(brief):return False
    from decimal import Decimal
    currencies={'USD':'USD','美元':'USD','美金':'USD','$':'USD','EUR':'EUR','欧元':'EUR','€':'EUR','GBP':'GBP','英镑':'GBP','£':'GBP','CNY':'CNY','人民币':'CNY','元':'CNY'}
    pattern='|'.join(re.escape(k) for k in currencies)
    def amounts(text):
        result=set()
        for m in re.finditer(r'('+pattern+r')\s*([0-9]+(?:\.[0-9]+)?)|([0-9]+(?:\.[0-9]+)?)\s*('+pattern+r')',text):
            result.add((currencies[m[1] or m[4]],Decimal(m[2] or m[3])))
        return result
    if not amounts(sentence)<=amounts(brief):return False
    country_aliases={'美国':r'美国|United States|USA','中国':r'中国|China','加拿大':r'加拿大|Canada|Canadian','澳大利亚':r'澳大利亚|Australia','新加坡':r'新加坡|Singapore','日本':r'日本|Japan'}
    for label,aliases in country_aliases.items():
        if label in sentence and not re.search(aliases,brief,re.I):return False
    if '免费' not in brief:
        for match in re.finditer('免费',sentence):
            before=sentence[max(0,match.start()-18):match.start()]
            if not re.search(r'(?:不能|无法|尚未|未能|不确定|不代表|是否)[^，,。；;！？]{0,12}$',before):return False
    if '国籍' in sentence and not re.search(r'nationality|citizenship|国籍',brief,re.I):return False
    if re.search(r'https?://\S+',sentence) and any(u not in brief for u in re.findall(r'https?://\S+',sentence)):return False
    if re.search(r'保证(?:成功|获批)|成功率(?:是|为|达到)|一定(?:获批|成功)|百分之',sentence):return False
    routes=[state['routes'][r] for r in state.get('current_route_refs',[])[:3] if r in state.get('routes',{})]
    complete=(state.get('current_route_coverage') or {}).get('search_complete',False)
    if routes and route_text_issues(sentence,routes,search_complete=complete):return False
    if not complete and re.search(r'查遍|全部查完|覆盖了所有|没有任何其他',sentence):return False
    if any(r.get('eligibility')!='PASS' for r in routes) and re.search(r'你(?:已|完全)?符合(?:所有)?(?:申请)?条件|你可以直接申请成功',sentence):return False
    if any(r.get('cost',{}).get('state')!='KNOWN' for r in routes) and re.search(r'(?:总共|总计|总费用|合计)(?:只需|为|是|仅)?\s*\d',sentence):return False
    return True


def narrate(provider,question,answer,state,history,emit):
    details=concise_details(state,answer,question) if re.search(r'核实|条件|资格|证件|居住|申请步骤',question) and not state.get('current_research_results') else []
    brief=answer['text']
    evidence=brief+'\n'+json.dumps(details,ensure_ascii=False)
    pending='';released=[];rejected=False
    prompt=json.dumps({'question':question,'verified_brief':brief,'details':details,
                       'task_context':state.get('task_context',{})},ensure_ascii=False,separators=(',',':'))
    def publish(part):
        nonlocal rejected
        part=re.sub(r'(?m)^\s*\d+\.\s*','',part).replace('**','')
        if '完整国家名单见步骤详情' in evidence:
            part=re.sub(r'[（(](?:如|例如|比如)[^）)]*[）)]','',part)
        if not released:part=re.sub(r'^\s*(?:另外|此外|最后)[，,]','',part)
        if state.get('current_research_results') and not re.search(r'资格|证件|条件|居住',question):
            if re.search(r'如果你|建议你|需要你|缺少你的|你.*提供',part):return
            if any(word in part and word not in brief for word in ('证件','资格','居住','参与历史','截止','时区')):return
        if state.get('public_task_active') and re.search(r'通常|一般都|有时会|经常会',part) and not any(word in brief for word in ('通常','一般都','有时会','经常会')):return
        if (state.get('public_task_active') or state.get('unrestricted_route_active')) and re.search(r'如果.*(?:具体|特定|偏好|目标|感兴趣)|请.*(?:目标|偏好)',part):return
        if guard_sentence(part,evidence,state):
            released.append(part);emit('text_delta',{'text':part})
        else:rejected=True
    for chunk in provider.stream_text(system_prompt=PROMPT,user_prompt=prompt):
        pending+=chunk
        if len(pending)+sum(map(len,released))>4000:raise ValueError('NARRATION_TOO_LONG')
        while (match:=re.search(r'[。！？\n]',pending)):
            part=pending[:match.end()];pending=pending[match.end():]
            publish(part)
    if pending:publish(pending)
    text=''.join(released).strip()
    if not text:
        text=brief if not re.search(r'[{}]',brief) else '已取得相关资料，但这次没能可靠地整理成说明。已核实的费用和完整条件保留在卡片中，未知项仍需核对。'
        emit('text_delta',{'text':text})
    answer['text']=text;answer['presentation_policy']='GROUNDED_NATURAL_LANGUAGE'
    if rejected:answer['narration_repaired']=True
    return answer
