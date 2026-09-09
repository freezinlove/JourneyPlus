"""Business receipts map to UI events outside the generic runtime."""
def result_events(result):
    if result.error:return []
    data=result.data
    events=[]
    if data.get('presentation_ref'):
        events.append(('presentation.created',{'presentation_ref':data['presentation_ref'],'blocks':data.get('blocks',[])}))
    if data.get('operation_ref'):
        after=data.get('after') or {};before=data.get('before') or {}
        label=' '.join(v for v in [after.get('program_name',before.get('program_name')),after.get('tier_name',before.get('tier_name'))] if v)
        summary=('已保存：' if after else '已删除：')+label if label else '等待任务操作已完成'
        if after.get('identity_status')=='NEEDS_CONFIRMATION':
            summary='已记录原始会籍陈述（名称待核对）：'+(after.get('display_statement') or label)
        if not label and after.get('status'):
            summary='等待任务：'+{'ACTIVE':'条件已就绪','NEEDS_RECONFIRMATION':'已保存，条件待确认，尚不可运行','CANCELLED':'已取消','RESULT_PENDING':'已有待查看结果'}.get(after['status'],after['status'])
        if data.get('outcome')=='NOOP':summary='内容未变更：'+label
        events.append(('operation.applied',{'operation_ref':data['operation_ref'],'summary':summary,'outcome':data.get('outcome'),
            'original_statements':(after.get('source_record') or before.get('source_record') or {}).get('original_statements',[])}))
    return events
