"""Capability metadata; handlers may be added without changing the runtime."""
from journeyplus.agent.harness.contracts import ToolDefinition, ToolResult
from .contracts import INPUTS
from .results import OUTPUTS

METADATA = {
    'catalog.lookup': ('Search program and tier names and aliases. Optional; other tools accept names directly.', 'READ', 10, '查找名称目录'),
    'activity.read': ('Read published activity overview, detail, evidence or changes at an explicit version. selector is an object: {"query":"program name"} or {"ref":"activity:UUID@VERSION"}, never a string. Returns brief links and expandable material refs.', 'READ', 15, '读取活动资料'),
    'routes.evaluate': ('Search published routes; names work directly without looking up IDs first. Search requires query OR query_ref+patch OR query_ref+cursor. Candidate from/to are endpoints; intermediate nodes are not destinations. Inspect/compare retrieve only the supplied candidate.ref values in route_refs, without applying a new target filter. Candidate requirements are summaries; inspect for full detail.', 'READ', 10, '计算会籍路径'),
    'holdings.read': ('Read saved user memberships, including unresolved names and revisions.', 'READ', 5, '读取已存会籍'),
    'holdings.write': ('Create/update/delete a user-authorized membership with verbatim user authorization, operation key and revision. Explicitly authorized unresolved names can be saved. Successful receipt proves the write.', 'USER_WRITE', 10, '更新用户会籍'),
    'workspace.read': ('Retrieve full conversation history, artifacts, actual presentations or notes. History searches include older messages and neighboring context.', 'READ', 5, '找回工作区资料'),
    'workspace.note': ('Replace temporary task notes with explicit revision and source references. Notes are model-authored context, not user authorization.', 'WORKSPACE_WRITE', 5, '保存任务笔记'),
    'web.search': ('Discover real public StatusMatcher company/report links; optional web backend may be unavailable. Search snippets are leads, not verified facts.', 'READ', 20, '发现公开页面'),
    'web.read': ('Read bounded text and real links from public HTTPS. Continue next_cursor with the same URL/sections for unread text and links; refresh starts a new snapshot. Page refs preserve the original for parsing. No login or scripts.', 'READ', 20, '读取公开网页'),
    'research.parse': ('Parse previously read StatusMatcher reports without requiring a published route. Preserve original identities and unknown comparability.', 'READ', 10, '解析申请经验'),
    'display.present': ('Show selected objects in exactly the supplied order, roles and comparison columns. Returns actual display receipt. Can supply only optional next-step suggestions.', 'WORKSPACE_WRITE', 10, '展示结果'),
    'waiting.manage': ('List or explicitly create/update/cancel a deterministic future check of published knowledge. One active goal. Writes require user authorization and an operation key.', 'USER_WRITE', 10, '管理等待任务'),
}


def definitions(handlers):
    async def unavailable(args, ctx):
        return ToolResult.failure('UNAVAILABLE','Capability not available in this runtime assembly',status='UNAVAILABLE')
    return [ToolDefinition(name=name,description=description,input_model=INPUTS[name],handler=handlers.get(name,unavailable),
                          effect=effect,timeout_seconds=timeout,progress_label=label,output_model=OUTPUTS[name],
                          operation_result_max_bytes=({'inspect':24000,'compare':24000} if name=='routes.evaluate' else
                                                      {'detail':24000,'evidence':24000} if name=='activity.read' else {}),
                          result_budget_field='view' if name=='activity.read' else 'operation',
                          operation_effects={'list':'READ','create':'USER_WRITE','update':'USER_WRITE','cancel':'USER_WRITE'} if name=='waiting.manage' else {})
            for name,(description,effect,timeout,label) in METADATA.items()]
