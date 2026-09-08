"""Independent Agent process and maintenance entry points."""
from argparse import ArgumentParser
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .adapters.config import AgentConfig
from .adapters.model import AgentModel
from .composition import compose_business
from journeyplus.config import Settings


def main():
    parser=ArgumentParser()
    parser.add_argument('--port',type=int,default=8013)
    parser.add_argument('--maintenance',action='store_true')
    parser.add_argument('--no-model',action='store_true',help='Model-free preview; never construct a model client or run a probe')
    args=parser.parse_args()
    settings=Settings.from_env()
    factory=sessionmaker(create_engine(settings.database_url),expire_on_commit=False)
    if args.maintenance:
        from .services.identities import IdentityService
        from .services.user_memory import UserMemory
        from .services.waiting import WaitingService
        from .adapters.persistence import SessionStore
        print({'cleanup':SessionStore(factory).cleanup(),'waiting':WaitingService(factory,UserMemory(factory,IdentityService())).check()})
        return
    if args.no_model:
        from .adapters.unconfigured import UnconfiguredModel
        runtime,store=compose_business(factory,UnconfiguredModel(),network_enabled=False)
    else:
        config=AgentConfig.from_env()
        runtime,store=compose_business(factory,AgentModel(config),network_enabled=config.network_enabled)
    from journeyplus.product.agent_api import create_agent_app
    import uvicorn
    uvicorn.run(create_agent_app(runtime,store),host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
