"""Capability metadata; handlers may be added without changing the runtime."""
from journeyplus.agent.harness.contracts import ToolDefinition, ToolResult
from .contracts import INPUTS
from .results import OUTPUTS
from .projection import trim_for, model_view_for

METADATA = {
    'catalog.lookup': ('Search program and tier names and aliases. Optional; other tools accept names directly.', 'READ', 10, '查找名称目录'),
    'activity.read': ('Use overview/detail structured facts when they answer the question. Read originals only for a specific unanswered question after checking details, or an explicit user request for original text; do not reread to reconfirm available facts. view=evidence lists archived source documents. view=original with section_refs=["document:UUID"] returns ONE complete archived page/article directly, including tables and footnotes (also LoyaltyLobby). No chunks or fact-field substitutes. selector: {"query":"program name"} or {"ref":"activity:UUID@VERSION"}.', 'READ', 15, '读取活动资料'),
    'routes.evaluate': ('Find shortest paths to highest reachable target tiers, with merged prefixes. Only free_only affects payment; no region or amount filters. Results contain free/paid flags; activity.read provides prices and regional details on request. Search routes from AIWorkflow official and article mappings; names work directly without looking up IDs first. Search requires query OR query_ref with optional patch/cursor; unpatched fields are inherited and query_context records their origin. Candidate from/to are endpoints; intermediate nodes are not destinations. Inspect/compare retrieve only the supplied candidate.ref values in route_refs, without applying a new target filter. Inspect retrieves selected steps; activity.read retrieves application conditions.', 'READ', 10, '计算会籍路径'),
    'holdings.read': ('Read saved memberships and their current validity. Default lists usable records with excluded expired records explained; holding_refs reads the specified record even when expired. An expired membership is not a valid matching source. No expiry recorded does not mean permanent validity.', 'READ', 5, '读取已存会籍'),
    'holdings.write': ('Create/update/delete a user-requested membership. Update/delete need holding_ref and expected_revision; create needs identity. Unresolved names can be saved. Returns outcome, entity and changes; full receipt is retrievable.', 'USER_WRITE', 10, '更新用户会籍'),
    'workspace.read': ('Retrieve history, artifacts, presentations or notes. Route archives begin with business overviews, followed by full paginated records. Use the overview route ref with routes.evaluate inspect for route facts; activity.read for activity facts. History search includes older neighboring messages.', 'READ', 5, '找回工作区资料'),
    'workspace.note': ('Replace temporary task notes with content and the observed revision. The service records the current turn automatically. Notes are model-authored context, not user authorization.', 'WORKSPACE_WRITE', 5, '保存任务笔记'),
    'web.search': ('Discover real public StatusMatcher company/report links; optional web backend may be unavailable. Search snippets are leads, not verified facts.', 'READ', 20, '发现公开页面'),
    'web.read': ('Read bounded text and real links from public HTTPS. Continue next_cursor with the same URL/sections for unread text and links; refresh starts a new snapshot. StatusMatcher report reads also return structured report fields and a reusable report_ref for workspace.read, experience cards and research_refs attachments. Report text appears once in text; next_cursor continues it. Page refs preserve the original. No login or scripts.', 'READ', 20, '读取公开网页'),
    'display.present': ('Show selected objects in supplied order and roles. route_graph/comparison take candidate.ref (#route:), never #step: or an archive root. Wrong step refs return matching route choices for you to select. Returns actual display receipt; suggestions alone are allowed.', 'WORKSPACE_WRITE', 10, '展示结果'),
    'waiting.manage': ('Wait for matching membership paths under the free/paid filter. Checks pause at the first hit (RESULT_PENDING); this is not ongoing price, region or eligibility monitoring. list: only limit/cursor. create/update: exactly one of query or query_ref. create: omit goal_ref/expected_revision, including nulls. update/cancel: require goal_ref/expected_revision. cancel: no query. All writes: omit limit/cursor. One active goal; unresolved identities need reconfirmation. Readiness is not a matching route.', 'USER_WRITE', 10, '管理等待任务'),
}


def definitions(handlers):
    async def unavailable(args, ctx):
        return ToolResult.failure('UNAVAILABLE','Capability not available in this runtime assembly',status='UNAVAILABLE')
    return [ToolDefinition(name=name,description=description,input_model=INPUTS[name],handler=handlers.get(name,unavailable),
                          effect=effect,version=('identity-v1' if name in {'catalog.lookup','routes.evaluate','holdings.read','holdings.write'}
                              else '9' if name=='activity.read' else '8'),trim_projection=trim_for(name),model_projection=model_view_for(name),timeout_seconds=timeout,progress_label=label,output_model=OUTPUTS[name],
                          complete_result_operations=('original',) if name=='activity.read' else (),
                          operation_result_max_bytes=({'inspect':24000,'compare':24000} if name=='routes.evaluate' else
                                                      {'detail':24000,'evidence':24000} if name=='activity.read' else {}),
                          result_budget_field='view' if name=='activity.read' else 'operation',
                          operation_effects={'list':'READ','create':'USER_WRITE','update':'USER_WRITE','cancel':'USER_WRITE'} if name=='waiting.manage' else {})
            for name,(description,effect,timeout,label) in METADATA.items()]
