"""Read-only schema inventory and row fingerprints; no raw business data output."""
import hashlib
import json
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from journeyplus.config import Settings
from journeyplus.models import AgentInteraction
from journeyplus.agent.adapters.models import RunCheckpoint, Artifact, ToolCall, OperationReceipt, DeliveryRun, DeliveryEvent
from journeyplus.workspace_models import WorkspaceMessage, WorkspaceTurn
engine = create_engine(Settings.from_env().database_url)
with engine.connect() as connection:
    connection.execute(text('SET TRANSACTION READ ONLY'))
    connection.execute(text("SET TIME ZONE 'UTC'"))
    inspector = inspect(connection)
    tables = inspector.get_table_names()
    result = {'database': engine.url.database, 'migration': connection.execute(text('select version_num from alembic_version')).scalar(), 'tables': {}}
    for table in sorted(tables):
        quoted = engine.dialect.identifier_preparer.quote(table)
        rows = connection.execute(text(f'SELECT to_jsonb(t)::text FROM {quoted} t ORDER BY to_jsonb(t)::text')).scalars().all()
        result['tables'][table] = {'count': len(rows), 'sha256': hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(), 'columns': [c['name'] for c in inspector.get_columns(table)]}
    result['runtime_schema_gaps'] = {}
    for model in [AgentInteraction, RunCheckpoint, Artifact, ToolCall, OperationReceipt, DeliveryRun, DeliveryEvent, WorkspaceMessage, WorkspaceTurn]:
        name = model.__tablename__
        actual = set(result['tables'].get(name, {}).get('columns', []))
        missing = sorted(set(model.__table__.columns.keys()) - actual)
        if missing: result['runtime_schema_gaps'][name] = {'table_missing': name not in tables, 'missing_columns': missing}
Path(sys.argv[1]).write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({'database':result['database'],'migration':result['migration'],'table_count':len(tables),'runtime_schema_gaps':result['runtime_schema_gaps']},ensure_ascii=False))
