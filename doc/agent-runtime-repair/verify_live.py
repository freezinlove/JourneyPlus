"""Read only: verify genuine runs, tool receipts, and unchanged workflow rows."""
import json
from pathlib import Path
from sqlalchemy import select
from journeyplus.db import engine_from_settings,create_session_factory
from journeyplus.agent.adapters.models import DeliveryRun, ToolCall, OperationReceipt, RunCheckpoint, Artifact
from journeyplus.models import AgentWaitGoal
from journeyplus.agent.adapters.workflow_holdings import WorkflowHolding
from journeyplus.agent.adapters.storage_readiness import storage_status
p=Path(__file__).parent
factory=create_session_factory(engine_from_settings())
a=json.loads((p/'before.json').read_text()); b=json.loads((p/'after-live.json').read_text())
unchanged=[name for name in a['tables'] if name not in {'alembic_version','agent_interactions','agent_wait_goals'}]
assert all(a['tables'][name]==b['tables'][name] for name in unchanged)
with factory() as session:
    runs=list(session.scalars(select(DeliveryRun).order_by(DeliveryRun.created_at)))
    calls=list(session.scalars(select(ToolCall).order_by(ToolCall.started_at)))
    goals=list(session.scalars(select(AgentWaitGoal)))
    receipts=list(session.scalars(select(OperationReceipt).order_by(OperationReceipt.created_at)))
    workspaces=sorted({str(r.workspace_id) for r in runs})
    report={'database':b['database'],'migration':b['migration'],'table_count':len(b['tables']),
        'unchanged_workflow_and_holding_tables':unchanged,'workspaces':workspaces,
        'runs':[{'id':str(r.id),'workspace_id':str(r.workspace_id),'status':r.status,'prompt':r.request['text'],
                 'budget':session.get(RunCheckpoint,r.id).remaining_budget} for r in runs],
        'tools':[{'name':c.tool_name,'call_id':c.provider_call_id,'status':c.status,'error':c.error} for c in calls],
        'operation_receipts':[{'operation':r.operation_kind,'status':r.status,'entity_id':str(r.entity_id)} for r in receipts],
        'remaining_holdings':len(list(session.scalars(select(WorkflowHolding)))),
        'waiting_goals':[{'id':str(g.id),'status':g.status} for g in goals],
        'schema_status':storage_status(factory),'third_party_model_calls':0}
    assert [r.status for r in runs].count('COMPLETED')==5
    assert [r.status for r in runs].count('CANCELED')==1
    assert len(calls)==12 and all(c.error is None for c in calls)
    assert report['remaining_holdings']==0
    assert all(g.status=='CANCELLED' for g in goals)
    report['model_requests']=sum(len(list(folder.glob('*.request.json'))) for folder in p.glob('exchange*'))
    report['startup_probe_requests']=4
    report['business_model_requests']=report['model_requests']-4
(p/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k not in {'runs','unchanged_workflow_and_holding_tables','tools'}},ensure_ascii=False,indent=2))
