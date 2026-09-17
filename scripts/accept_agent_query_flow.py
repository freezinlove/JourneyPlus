"""Live acceptance against configured model/database; creates read-only test conversations.
Does not change the account's current workspace or saved memberships.
Run with .venv/bin/python scripts/accept_agent_query_flow.py.
"""
import asyncio,json,time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from journeyplus.config import Settings
from journeyplus.agent.adapters.config import AgentConfig
from journeyplus.agent.adapters.model import AgentModel
from journeyplus.agent.composition import compose_business
async def main():
 model=AgentModel(AgentConfig.from_env()); await model.initialize()
 factory=sessionmaker(create_engine(Settings.from_env().database_url),expire_on_commit=False)
 runtime,store=compose_business(factory,model)
 for text in ['我有万豪 Platinum Elite，只查询匹配进汉莎的路径，不要反向查询。','给我汉莎匹配图','给我汉莎匹配图']:
  w=store.create();r=store.start(w['id'],text,w['id'],0);t=time.monotonic()
  await runtime.run(r['run_id']);events,status=store.events(w['id'],r['run_id']);v=store.read(w['id'])
  calls=[p for m in v['messages'] for p in m['content'] if p['type']=='tool_call']
  answers=[p.get('text') for m in v['messages'] if m['role']=='assistant' for p in m['content'] if p['type']=='text']
  assert status == 'COMPLETED', status
  if text == '给我汉莎匹配图':
   assert not calls and not v['presentation_refs'], 'Ambiguous request must clarify without tools'
   assert any('方向' in (a or '') or '还是' in (a or '') for a in answers), 'Clarification must not assume direction'
  else:
   assert [c['name'] for c in calls] == ['routes.evaluate'], calls
   assert not v['presentation_refs'], 'No-match must not create a substitute table'
  print(json.dumps({'request':text,'seconds':round(time.monotonic()-t,1),'status':status,'calls':calls,'answers':answers,'presentations':v['presentation_refs']},ensure_ascii=False),flush=True)
 await model.close()
asyncio.run(main())
