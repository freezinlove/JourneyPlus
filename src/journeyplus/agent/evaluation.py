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
    return failures
