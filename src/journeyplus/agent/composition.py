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
    if services and services.get('waiting_enabled') is False:
        instructions += '\n当前等待功能已关闭，后台不会检查等待任务。不要承诺创建等待或自动追踪；用户仍可主动查询匹配路径。\n'
    store = SessionStore(factory, getattr(getattr(model, 'config', None), 'model', 'test'), digest(instructions))
    registry = Registry()
    for definition in definitions:
        registry.register(definition)
    from .adapters.workspace_access import WorkspaceAccess
    ports = RuntimePorts(model, store, store.artifacts, registry, store, monotonic, WorkspaceAccess(store))
    config=getattr(model,'config',None)
    budget_limits={'soft':{'input_tokens':getattr(config,'input_token_soft',450000)},
                   'hard':{'input_tokens':getattr(config,'input_token_limit',500000)},
                   'context_tokens':getattr(config,'context_token_budget',500000)}
    return Runtime(ports, instructions, services,budget_limits), store


def compose_business(factory, model, *, network_enabled=False, read_factory=None, knowledge_port=None, waiting_enabled=None):
    from .services.identities import IdentityService
    from .services.user_memory import UserMemory
    from .services.waiting import WaitingService
    from .services.research import PublicResearch
    from .tools.registration import definitions
    from .tools import knowledge, routes, holdings, workspace, research, presentation, waiting
    import json, os
    if waiting_enabled is None:
        waiting_enabled = os.getenv('JOURNEYPLUS_AGENT_WAITING_ENABLED', 'false').lower() == 'true'
    from .services.search import HttpJsonSearch
    search=HttpJsonSearch(json.loads(os.environ['JOURNEYPLUS_AGENT_SEARCH_CONFIG']) if os.environ.get('JOURNEYPLUS_AGENT_SEARCH_CONFIG') else None)
    from .services import workspace as workspace_service, display
    from .adapters.user_data import UserData
    from .services.route_query import RouteQueries
    from .adapters.connections import knowledge_factory
    if read_factory is None:read_factory,close_read_connection=knowledge_factory(factory)
    else:close_read_connection=None
    if knowledge_port is None:
        from .adapters.workflow_knowledge import WorkflowKnowledgePort
        knowledge_port=WorkflowKnowledgePort(read_factory)
    identities=IdentityService(getattr(knowledge_port,"catalog",None))
    user_data=getattr(knowledge_port,"user_data",UserData)(factory)
    queries=RouteQueries(knowledge_port,user_data,identities)
    memory_type=getattr(knowledge_port,'memory_type',UserMemory)
    memory=memory_type(factory,identities,knowledge_port)
    services={'workspace_read':workspace_service.read,'workspace_note':workspace_service.note,'display':display.present,'knowledge':knowledge_port,'user_data':user_data,'route_queries':queries,'identities':identities,'user_memory':memory,
              'waiting':WaitingService(factory,memory,queries),'research':PublicResearch(network_enabled,search_backend=search)}
    services['waiting_enabled'] = waiting_enabled
    handlers={'catalog.lookup':knowledge.catalog,'activity.read':knowledge.activity,'routes.evaluate':routes.evaluate,
              'holdings.read':holdings.read,'holdings.write':holdings.write,'workspace.read':workspace.read,'workspace.note':workspace.note,
              'web.search':research.search,'web.read':research.read,
              'display.present':presentation.present,'waiting.manage':waiting.manage}
    from .services.snapshots import snapshot_for
    registered=[definition for definition in definitions(handlers)
                if waiting_enabled or definition.name != 'waiting.manage']
    for definition in registered:
        definition.snapshot=snapshot_for(definition.name,services['knowledge'],factory)
        if definition.name in {'catalog.lookup','activity.read','routes.evaluate'}:
            definition.availability=knowledge_port.availability
        if definition.name=='web.search':
            definition.availability=lambda:{'statusmatcher':'AVAILABLE' if network_enabled else 'DISABLED',
                'web':'AVAILABLE' if network_enabled and search.enabled else (search.failure or 'DISABLED')}
        elif definition.name=='web.read':
            definition.availability=lambda:{'status':'AVAILABLE' if network_enabled else 'DISABLED'}
    runtime,store=compose(factory,model,registered,services)
    store.published_refs=services['knowledge']
    from .adapters.workflow_knowledge import WorkflowKnowledgePort
    if isinstance(knowledge_port, WorkflowKnowledgePort):
        from .adapters.activity_access import ActivityViews, ActiveArtifacts, ActiveWorkspace
        views = ActivityViews(knowledge_port, store.artifacts, store)
        runtime.ports.views = views
        runtime.ports.artifacts = ActiveArtifacts(store.artifacts, views)
        runtime.ports.workspace = ActiveWorkspace(store, views)
    services['close_read_connection']=close_read_connection
    services['maintenance']=lambda:{'cleanup':store.cleanup(),
        'waiting':services['waiting'].check() if waiting_enabled else {'status':'DISABLED','model_calls':0}}
    return runtime,store
