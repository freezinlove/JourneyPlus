"""Read-only verification of the storage actually required by this Harness."""
from sqlalchemy import inspect, select
from sqlalchemy.exc import SQLAlchemyError
from journeyplus.models import AgentInteraction, AgentWaitGoal
from journeyplus.workspace_models import WorkspaceMessage, WorkspaceTurn
from .models import RunCheckpoint, Artifact, ToolCall, OperationReceipt, DeliveryRun, DeliveryEvent

RUNTIME_MODELS = (AgentInteraction, AgentWaitGoal, WorkspaceMessage, WorkspaceTurn,
                  RunCheckpoint, Artifact, ToolCall, OperationReceipt, DeliveryRun, DeliveryEvent)


def storage_status(factory):
    try:
        with factory() as session:
            inspector = inspect(session.connection())
            present = set(inspector.get_table_names())
            missing = {}
            for model in RUNTIME_MODELS:
                table = model.__table__
                columns = {c['name'] for c in inspector.get_columns(table.name)} if table.name in present else set()
                absent = sorted(set(table.columns.keys()) - columns)
                if absent:
                    missing[table.name] = absent
            if missing:
                return {'status': 'UNAVAILABLE', 'code': 'AGENT_STORAGE_SCHEMA_MISMATCH', 'missing': missing,
                        'message': 'Agent 运行存储尚未就绪，请应用当前正式模型的 Agent 迁移。'}
            # Confirm SELECT permission as well as schema presence, without reading user records.
            for model in RUNTIME_MODELS:
                session.execute(select(model).limit(0))
            return {'status': 'AVAILABLE', 'code': None, 'missing': {}}
    except SQLAlchemyError:
        return {'status': 'UNAVAILABLE', 'code': 'DATABASE_UNAVAILABLE', 'missing': {},
                'message': '暂时无法连接或读取 Agent 运行存储，请检查数据库服务。'}
