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
        if data.get('outcome')=='NOOP':summary='记录已存在，无需重复保存：'+label
        events.append(('operation.applied',{'operation_ref':data['operation_ref'],'summary':summary,'outcome':data.get('outcome')}))
    return events
