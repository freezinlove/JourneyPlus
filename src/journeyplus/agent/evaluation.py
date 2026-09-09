"""Structural evaluation assertions. Passing never implies semantic approval."""


def assess_case(expect,messages,journal_changed):
    calls={}
    results=[]
    for message in messages:
        turn=message.metadata.get('turn_id')
        for part in message.content:
            if part.type=='tool_call':calls[(turn,part.call_id)]=part
            elif part.type=='tool_result':results.append((calls.get((turn,part.call_id)),part.result))
    failures=[]
    if expect.get('zero_tools') and calls:failures.append('EXPECTED_ZERO_TOOLS')
    if expect.get('tool') and not any(call and call.name==expect['tool'] and
            result['status'] in {'OK','PARTIAL','EMPTY'} and not result.get('error') for call,result in results):
        failures.append('MISSING_EXPECTED_CAPABILITY')
    if expect.get('no_user_write') and journal_changed:failures.append('UNAUTHORIZED_USER_WRITE')
    if expect.get('authorized_write') and not any(result.get('data',{}).get('operation_ref') and
            result['data'].get('outcome') in {'APPLIED','NOOP'} for _,result in results):
        failures.append('MISSING_AUTHORIZED_RECEIPT')
    for field,expected in expect.get('query_fields',{}).items():
        for call,result in results:
            if not call or call.name!='routes.evaluate' or call.arguments.get('operation')!='search' or result.get('error'):continue
            value=result.get('data',{}).get('effective_query',{})
            for key in field.strip('/').split('/'):
                value=value.get(key) if isinstance(value,dict) else None
            if value!=expected:failures.append('QUERY_FIELD_MISMATCH:'+field);break
    for field,expected in expect.get('holding_fields',{}).items():
        writes=[result for call,result in results if call and call.name=='holdings.write' and not result.get('error') and result.get('data',{}).get('after')]
        if not writes or writes[-1]['data']['after'].get(field)!=expected:failures.append('HOLDING_FIELD_MISMATCH:'+field)
    if expect.get('waiting_status') and not any(call and call.name=='waiting.manage' and
            result.get('data',{}).get('after',{}).get('status')==expect['waiting_status'] for call,result in results):
        failures.append('WAITING_STATE_MISMATCH')
    if expect.get('presentation_columns'):
        selected=[block for call,result in results if call and call.name=='display.present' and not result.get('error')
                  for block in result.get('data',{}).get('blocks',[])]
        if not any(set(expect['presentation_columns'])<=set(block.get('columns',[])) for block in selected):
            failures.append('PRESENTATION_COLUMNS_MISSING')
    if expect.get('per_turn'):
        groups=[]
        for message in messages:
            if message.role=='user':groups.append([])
            if groups:groups[-1].append(message)
        for index,checks in expect['per_turn'].items():
            number=int(index)
            if number>=len(groups):failures.append('MISSING_TURN:'+index)
            else:failures.extend('TURN_'+index+':'+failure for failure in assess_case(checks,groups[number],False))
    return list(dict.fromkeys(failures))
