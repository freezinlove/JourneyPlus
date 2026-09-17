"""Isolated UI acceptance server. Never connects to the configured product database."""
import tempfile
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from journeyplus.models import Base
import journeyplus.accounts
import journeyplus.agent.adapters.models
from journeyplus.accounts import create_account
from journeyplus.user_scope import OWNER_ID
from journeyplus.product.api import create_product_app
from journeyplus.agent.harness.contracts import ModelEvent,Capabilities
from tests.test_agent_workflow_reads import seed

class TestModel:
    def capabilities(self):return Capabilities(native_tools=True,streaming=True,context_window=32768,max_output=4096)
    async def initialize(self):pass
    async def stream(self,messages,definitions,limits,cancel_token):
        yield ModelEvent(type='text_delta',text='这是隔离验收环境的流式回复，未调用真实模型。')
        yield ModelEvent(type='turn_end',finish_reason='stop')

root=Path(tempfile.mkdtemp(prefix='journeyplus-clients-'))
factory=sessionmaker(create_engine('sqlite:///'+str(root/'acceptance.sqlite'),connect_args={'check_same_thread':False}),expire_on_commit=False)
Base.metadata.create_all(factory.kw['bind'])
create_account(factory,'client-test','Client-test-2026!',identity=OWNER_ID)
seed(factory)
app=create_product_app(factory,agent_model=TestModel())
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8019)
