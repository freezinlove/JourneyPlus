"""Capability metadata; handlers may be added without changing the runtime."""
from journeyplus.agent.harness.contracts import ToolDefinition, ToolResult
from .contracts import INPUTS
from .results import OUTPUTS
from .projection import trim_for, model_view_for

METADATA = {
    'catalog.lookup': ('Search program and tier names and aliases. Optional; other tools accept names directly.', 'READ', 10, '查找名称目录'),
    'activity.read': ('Read AIWorkflow activity overview, structured detail, source directory or changes at a FactSet/analysis version. Original text requires explicit document:UUID:chunk section_refs. selector is an object: {"query":"program name"} or {"ref":"activity:UUID@VERSION"}, never a string. Returns brief links and expandable material refs.', 'READ', 15, '读取活动资料'),
    'routes.evaluate': ('Search routes from AIWorkflow official and article mappings; names work directly without looking up IDs first. Search requires query OR query_ref with optional patch/cursor; unpatched fields are inherited and query_context records their origin. Candidate from/to are endpoints; intermediate nodes are not destinations. Inspect/compare retrieve only the supplied candidate.ref values in route_refs, without applying a new target filter. Candidate requirements are summaries; inspect for full detail.', 'READ', 10, '计算会籍路径'),
    'holdings.read': ('Read saved user memberships, including unresolved names and revisions.', 'READ', 5, '读取已存会籍'),
    'holdings.write': ('Create/update/delete a user-requested membership. Update/delete need holding_ref and expected_revision; create needs identity. Unresolved names can be saved. Returns outcome, entity and changes; full receipt is retrievable.', 'USER_WRITE', 10, '更新用户会籍'),
    'workspace.read': ('Retrieve full conversation history, artifacts, actual presentations or notes. History searches include older messages and neighboring context.', 'READ', 5, '找回工作区资料'),
    'workspace.note': ('Replace temporary task notes with content and the observed revision. The service records the current turn automatically. Notes are model-authored context, not user authorization.', 'WORKSPACE_WRITE', 5, '保存任务笔记'),
    'web.search': ('Discover real public StatusMatcher company/report links; optional web backend may be unavailable. Search snippets are leads, not verified facts.', 'READ', 20, '发现公开页面'),
    'web.read': ('Read bounded text and real links from public HTTPS. Continue next_cursor with the same URL/sections for unread text and links; refresh starts a new snapshot. Page refs preserve the original for parsing. No login or scripts.', 'READ', 20, '读取公开网页'),
    'research.parse': ('Parse previously read StatusMatcher reports without requiring a published route. Preserve original identities and unknown comparability.', 'READ', 10, '解析申请经验'),
    'display.present': ('Show selected objects in exactly the supplied order, roles and comparison columns. Returns actual display receipt. Can supply only optional next-step suggestions.', 'WORKSPACE_WRITE', 10, '展示结果'),
    'waiting.manage': ('Manage user-requested future checks. list: only limit/cursor. create/update: exactly one of query or query_ref. create: omit goal_ref/expected_revision, including nulls. update/cancel: require goal_ref/expected_revision. cancel: no query. All writes: omit limit/cursor. One active goal; unresolved identities need reconfirmation. Readiness is not a matching route.', 'USER_WRITE', 10, '管理等待任务'),
}


def definitions(handlers):
    async def unavailable(args, ctx):
        return ToolResult.failure('UNAVAILABLE','Capability not available in this runtime assembly',status='UNAVAILABLE')
    return [ToolDefinition(name=name,description=description,input_model=INPUTS[name],handler=handlers.get(name,unavailable),
                          effect=effect,version='5',trim_projection=trim_for(name),model_projection=model_view_for(name),timeout_seconds=timeout,progress_label=label,output_model=OUTPUTS[name],
                          operation_result_max_bytes=({'inspect':24000,'compare':24000} if name=='routes.evaluate' else
                                                      {'detail':24000,'evidence':24000} if name=='activity.read' else {}),
                          result_budget_field='view' if name=='activity.read' else 'operation',
                          operation_effects={'list':'READ','create':'USER_WRITE','update':'USER_WRITE','cancel':'USER_WRITE'} if name=='waiting.manage' else {})
            for name,(description,effect,timeout,label) in METADATA.items()]
