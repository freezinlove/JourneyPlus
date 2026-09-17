"""Live acceptance using configured model/knowledge; never changes current chat or holdings."""
import asyncio
import json
from time import monotonic
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from journeyplus.config import Settings
from journeyplus.agent.adapters.config import AgentConfig
from journeyplus.agent.adapters.model import AgentModel
from journeyplus.agent.composition import compose_business

async def main():
    engine=create_engine(Settings.from_env().database_url)
    model=AgentModel(AgentConfig.from_env())
    try:
        await model.initialize()
        runtime,store=compose_business(sessionmaker(engine,expire_on_commit=False),model)
        for prompt in ['用我保存的汉莎会籍，查免费匹配路径并展示。','用我保存的汉莎会籍查询进入全日空的路径。']:
            workspace=store.create()
            run=store.start(workspace['id'],prompt,workspace['id'],0)
            started=monotonic()
            await runtime.run(run['run_id'])
            events,status=store.events(workspace['id'],run['run_id'])
            messages=store.read(workspace['id'])['messages']
            calls=[part for msg in messages for part in msg['content'] if part['type']=='tool_call']
            timing=[event['payload'] for event in events if event['type']=='model.timing']
            report={'request':prompt,'run_id':run['run_id'],'status':status,'seconds':round(monotonic()-started,2),
                'calls':[{'name':call['name'],'arguments':call['arguments']} for call in calls],
                'timing':[{key:t.get(key) for key in ['attempt','context_prepare_ms','context_reused','elapsed_ms']} for t in timing]}
            print(json.dumps(report,ensure_ascii=False),flush=True)
            assert status=='COMPLETED'
            assert calls[0]['name']=='routes.evaluate' and calls[0]['arguments']['query']['sources']['saved_program']
            assert all(call['name']!='holdings.read' for call in calls)
            assert any(t.get('context_reused') for t in timing)
    finally:
        await model.close()
        engine.dispose()

if __name__=='__main__':asyncio.run(main())
