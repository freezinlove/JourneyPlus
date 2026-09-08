"""The only module that assembles runtime, adapters and business tools."""
from pathlib import Path
from time import monotonic
from .harness.contracts import RuntimePorts
from .harness.registry import Registry
from .harness.runtime import Runtime
from .adapters.persistence import SessionStore
from .adapters.artifacts import digest


def compose(factory, model, definitions=(), services=None):
    instructions = Path(__file__).with_name('instructions.md').read_text()
    store = SessionStore(factory, getattr(getattr(model, 'config', None), 'model', 'test'), digest(instructions))
    registry = Registry()
    for definition in definitions:
        registry.register(definition)
    ports = RuntimePorts(model, store, store.artifacts, registry, store, monotonic)
    config=getattr(model,'config',None)
    budget_limits={'soft':{'input_tokens':getattr(config,'input_token_soft',45000)},
                   'hard':{'input_tokens':getattr(config,'input_token_limit',60000)}}
    return Runtime(ports, instructions, services,budget_limits), store


def compose_business(factory, model, *, network_enabled=False, read_factory=None):
    from journeyplus.knowledge.access import KnowledgePort
    from .services.identities import IdentityService
    from .services.user_memory import UserMemory
    from .services.waiting import WaitingService
    from .services.research import PublicResearch
    from .tools.registration import definitions
    from .tools import knowledge, routes, holdings, workspace, research, presentation, waiting
    import json, os
    from .services.search import HttpJsonSearch
    search=HttpJsonSearch(json.loads(os.environ['JOURNEYPLUS_AGENT_SEARCH_CONFIG']) if os.environ.get('JOURNEYPLUS_AGENT_SEARCH_CONFIG') else None)
    from .services import workspace as workspace_service, display
    identities=IdentityService()
    memory=UserMemory(factory,identities)
    services={'workspace_read':workspace_service.read,'workspace_note':workspace_service.note,'display':display.present,'knowledge':KnowledgePort(read_factory or factory),'identities':identities,'user_memory':memory,
              'waiting':WaitingService(factory,memory),'research':PublicResearch(network_enabled,search_backend=search)}
    handlers={'catalog.lookup':knowledge.catalog,'activity.read':knowledge.activity,'routes.evaluate':routes.evaluate,
              'holdings.read':holdings.read,'holdings.write':holdings.write,'workspace.read':workspace.read,'workspace.note':workspace.note,
              'web.search':research.search,'web.read':research.read,'research.parse':research.parse,
              'display.present':presentation.present,'waiting.manage':waiting.manage}
    from .services.snapshots import snapshot_for
    registered=definitions(handlers)
    for definition in registered:
        definition.snapshot=snapshot_for(definition.name,services['knowledge'],factory)
    runtime,store=compose(factory,model,registered,services)
    store.published_refs=services['knowledge']
    services['maintenance']=lambda:{'cleanup':store.cleanup(),'waiting':services['waiting'].check()}
    return runtime,store
