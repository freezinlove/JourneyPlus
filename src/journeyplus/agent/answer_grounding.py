"""Conservative checks for formal claims; deterministic fallback preserves facts."""
import re
from decimal import Decimal


def _asserts(pattern,text):
    for match in re.finditer(pattern,text,re.I):
        before=text[max(0,match.start()-10):match.start()]
        if re.search(r'不能|无法|尚未|未明确|并非|不代表|不确定|是否',before):continue
        return True
    return False


def route_text_issues(text,routes,*,search_complete):
    issues=[]
    if any(route['challenge']=='UNKNOWN' for route in routes) and _asserts(r'无(?:需)?挑战|不需要挑战|没有挑战|no challenge|without (?:a )?challenge',text):
        issues.append('UNKNOWN_CHALLENGE_ASSERTED_NONE')
    if not search_complete and _asserts(r'仅此一条|唯一(?:的)?(?:路径|路线|方案)|只有(?:这)?一条(?:路径|路线)|仅有.{0,3}一条',text):
        issues.append('PARTIAL_SEARCH_ASSERTED_UNIQUE')
    conditions='\n'.join(c for route in routes for c in route['material_caveats'])
    residency_conditions=re.sub(r'\bresidence permits?\b','',conditions,flags=re.I)
    if re.search(r'government issued identity|passport|证件签发',conditions,re.I) and not re.search(r'\bresiden(?:ts?|ce|cy)\b|居住',residency_conditions,re.I) and re.search(r'居住(?:国|地)|country of residence',text,re.I):
        issues.append('DOCUMENT_COUNTRY_IS_NOT_RESIDENCY')
    if any(not r['cost']['is_proven_free'] for r in routes) and _asserts(r'免费(?:匹配|申请)|(?:匹配|申请)(?:是)?免费|无需(?:支付)?申请费',text):
        issues.append('UNPROVEN_FREE_ASSERTION')
    return issues


def verified_route_text(routes,*,search_complete,steps=None,question=""):
    lines=['按当前可核实资料，已找到以下路径：']
    for route in routes:
        path_steps=[(steps or {}).get(ref) for ref in route.get('step_refs',[])]
        if path_steps and all(path_steps):
            nodes=[path_steps[0]['from'] or '公开申请']+[step['to'] for step in path_steps]
            lines.append(' → '.join(nodes)+'。')
        else:
            lines.append(f"{route['from'] or '公开申请'} → {route['to']}。")
        totals=route['cost']['totals']
        if route['cost']['is_proven_free']:
            lines.append('申请费用明确免费。')
        elif totals and all(Decimal(str(item['amount']))==0 for item in totals):
            lines.append('已确认的费用项目为零，其他费用或适用性仍待核实。')
        elif totals:
            totals=[item for item in totals if Decimal(str(item['amount']))>0]
            amounts=[' '.join(x for x in [item['currency'],format(Decimal(str(item['amount'])).normalize(),'f')] if x) for item in totals]
            lines.append('已确认费用：'+'；'.join(amounts)+('（另有待核实费用）。' if route['cost']['state']!='KNOWN' else '。'))
        elif route['cost']['state']=='CONFLICT':lines.append('费用来源存在冲突，不能确定合计。')
        else:lines.append('费用或费用适用性仍需核实。')
        if route.get('classification')=='NEARBY':
            names={'free_only':'仅免费','max_amount':'金额上限','allow_challenge':'不接受挑战'}
            lines.append('此方案尚不满足当前条件：'+'、'.join(names.get(v,'查询条件') for v in route.get('violations',[]))+'。')
        elif route.get('classification')=='UNKNOWN':lines.append('是否满足当前查询条件仍有待核实。')
        lines.append({'UNKNOWN':'挑战要求尚未核实。','NONE':'资料明确不要求挑战。','REQUIRED':'此路径包含挑战要求。'}[route['challenge']])
        if route['eligibility']!='PASS':lines.append('申请资格仍需逐项核对，具体证件和其他条件请查看路径详情。')
    if re.search(r'证件|身份证|护照|passport|identity|document',question,re.I):
        clauses=[]
        for route in routes:
            for ref in route.get('step_refs',[]):
                for check in (steps or {}).get(ref,{}).get('constraint_checks',[]):
                    reason=check.get('reason','')
                    if check.get('topic')=='DOCUMENT_REQUIREMENT' or re.search(r'passport|identity|证件|护照',reason,re.I):
                        clauses.append(reason)
        if clauses:lines.append('证件要求（已绑定步骤的原文，未推断居住地）：\n'+'\n'.join(dict.fromkeys(clauses)))
        else:lines.append('本轮尚未核实具体证件要求，不能推断身份证或护照可以替代。')
    if not search_complete:lines.append('本次资料覆盖不完整，不能据此认定只有这些路径。')
    return '\n'.join(lines)


def verified_activity_prices(materials,question=''):
    """Render disclosed prices and their scope; never subtract unlike currencies."""
    lines=[];seen=set();currencies=set();seen_clauses=set()
    for material in reversed(materials):
        data=material.get('data',{})
        names={t['tier_ref']:t['tier_name'] for t in data.get('catalog',[]) if isinstance(t,dict) and 'tier_ref' in t}
        mentioned={ref for ref,name in names.items() if re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',question,re.I)}
        for fact in data.get('facts',[]):
            if fact.get('field')!='prices':continue
            for price in fact['value']:
                if mentioned and price.get('target_scope')=='EXACT' and price.get('target_tier_id') not in mentioned:continue
                ref=price['ref']
                if ref in seen:continue
                seen.add(ref)
                target=names.get(price.get('target_tier_id'),'该方案范围内等级')
                label=f"{fact['label']} · {target}"
                if price['known_state']=='KNOWN' and price.get('amount') is not None:
                    amount=format(Decimal(price['amount']).normalize(),'f')
                    currency=price.get('currency') or ''
                    if currency:currencies.add(currency)
                    lines.append(label+'：'+('明确免费' if Decimal(amount)==0 else f'{currency} {amount}')+'。')
                else:lines.append(label+'：费用待核实或存在冲突。')
                if price.get('availability')!='AVAILABLE':lines.append('费用适用性仍需核实。')
                role={'APPLICATION':'申请费','BUY_UP':'升级附加费','CHALLENGE_SPEND':'挑战消费','OTHER':'其他费用'}.get(price.get('fee_role'),price.get('fee_role',''))
                if role:lines.append('费用类型：'+role+'。')
                # Scope/exceptions are quoted intact, not freely paraphrased.
                clauses=[c.get('raw_text','') for c in price.get('conditions',{}).get('items',[])]
                raw=price.get('raw_text','')
                if '|' in raw:
                    clauses.extend(re.sub(r'^(?:[A-Z]{3}|US\$|[€£$])\s*[0-9][0-9,.]*\s*','',line.strip().strip('|').split('|')[-1].strip()) for line in raw.splitlines() if re.search(r'not available|except|exclud|only|must|required',line,re.I) and (target=='该方案范围内等级' or re.search(r'(?<!\w)'+re.escape(target.split()[-1])+r'(?!\w)',line,re.I)))
                elif raw:clauses.append(raw)
                clauses=[c for c in dict.fromkeys(clauses) if c and c not in seen_clauses]
                if clauses:lines.append('适用说明（原文）：\n'+ '\n'.join(clauses));seen_clauses.update(clauses)
        # Supplementary fees may have reliable text without a publishable target
        # mapping. Keep their qualification; never silently turn them into edges.
        for fact in data.get('facts',[]):
            if fact.get('field')!='caveats':continue
            for caveat in fact.get('value',[]):
                text=caveat.get('raw_text') or caveat.get('value') or ''
                if caveat.get('known_state')!='KNOWN' or not caveat.get('evidence_ids') or not isinstance(text,str):continue
                if text in seen_clauses or not re.search(r'fee|cost|费用|收费',text,re.I):continue
                if re.search(r'buy[- ]up|upgrade|升级',text,re.I):
                    lines.append('额外升级费用说明（须符合原文资格，不是通用申请费）：\n'+text)
                    seen_clauses.add(text)
    if not lines:return None
    lines.append('完整适用范围、来源条款与方案明细可在活动卡中查看。')
    if len(currencies)>1:lines.append('以上币种分别列示，未换汇，不能直接相减比较差额。')
    return '\n'.join(lines)


def verified_activity_validity(materials):
    lines=[];seen=set()
    for material in reversed(materials):
        for fact in material.get('data',{}).get('facts',[]):
            if fact.get('field')!='status_validity' or fact['ref'] in seen:continue
            seen.add(fact['ref']);wrapped=fact['value'];value=wrapped.get('value') or {}
            if wrapped.get('known_state')!='KNOWN' or value.get('kind')!='DURATION':continue
            duration=[]
            if value.get('months') is not None:duration.append(str(value['months'])+' 个月')
            if value.get('days') is not None:duration.append(str(value['days'])+' 天')
            anchor={'APPROVAL':'批准后','APPLICATION':'申请后','COMPLETION':'完成要求后'}.get(value.get('anchor'),'起算时间待核实，持续')
            if duration:lines.append(f"{fact['label']}：{anchor}{' '.join(duration)}。")
    return '\n'.join(dict.fromkeys(lines)) or None
