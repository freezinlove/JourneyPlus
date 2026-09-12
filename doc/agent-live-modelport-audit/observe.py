"""Read actual server readiness plus read-only SQL failure diagnostics."""
import json
from pathlib import Path
import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from journeyplus.config import Settings
from journeyplus.db import engine_from_settings, create_session_factory
from journeyplus.models import AgentInteraction
from journeyplus.agent.adapters.models import RunCheckpoint
from journeyplus.agent.adapters.config import AgentConfig
s=Settings.from_env()
config=AgentConfig.from_env()
result={'status': httpx.get('http://127.0.0.1:8013/v3/agent/status').json(), 'configuration': {'network_enabled': config.network_enabled, 'context_window':config.context_window, 'protocol':config.protocol,'knowledge_read_mode':s.knowledge_read_mode,'knowledge_user_writes_paused':s.knowledge_user_writes_paused},'sql_errors':[]}
factory=create_session_factory(engine_from_settings(s))
for model in [AgentInteraction, RunCheckpoint]:
    try:
        with factory() as session:
            session.execute(select(model).limit(0))
    except SQLAlchemyError as error:
        result['sql_errors'].append({'table':model.__tablename__,'type':type(error.orig).__name__,'sqlstate':getattr(error.orig,'sqlstate',None),'message':str(error.orig).split('\n')[0]})
Path(__file__).with_name('observation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
