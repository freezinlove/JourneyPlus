> 当前实施顺序与授权边界以 [实施总纲](charter.md) 为准：先完成系统侧人工双视角验收与本地架构收口，交用户审核；审核明确允许后才调用第三方模型 API（含探针）。原真实模型验收项保留待执行。

# 存储、上下文、用户记忆与恢复

## 1. 范围与现有表复用

当前项目是单用户本地产品；本change不声称已有多租户隔离。ExecutionContext的owner固定为服务端local-user，不能由模型参数传入。若之后引入多用户，必须在身份认证和全部查询增加owner边界，不能只让模型填写user_id。

复用：AgentInteraction、WorkspaceMessage、WorkspaceTurn、DeliveryRun/Event、StatusHolding、AgentWaitGoal、UserBusinessOperation。新会话 `schema_version='harness-2'`、prompt_version带instruction hash。旧workspace-1保持旧消息可读；新核心不接收其state中的语义标记。

AgentInteraction.state限制为：
```json
{"schema_version":2,"note_revision":0,"note_ref":null,"focus":null,
 "presentation_refs":[],"recent_artifact_refs":[],"import_source":null,
 "model_configuration_id":"..."}
```
禁止last_query隐式行为、task_context.intent、source_changed、target_scope、turn_route_plan等执行标记。查询历史是不可变artifact；笔记是可修改参考；明确输入始终可以新建查询。

WorkspaceMessage.content新增通用parts及metadata，role复用USER/ASSISTANT/TOOL；ordinal按workspace内append sequence递增，不使用旧每轮固定2条公式。现有唯一约束可以保留，追加时锁会话或使用原子sequence，不能在网络等待时持锁。完整tool结果存在artifact，消息保留摘要+ref+call_id。

## 2. 新增数据库结构

实施时在当前唯一Alembic head后新增一个additive revision，不预先占用序号；单独migration不改正式知识表。

| 表 | 字段与约束 |
|---|---|
| agent_run_checkpoints | run_id UUID PK/FK delivery_runs CASCADE；workspace_id FK；turn_id FK agent_turns；phase varchar；model_attempt int；pending_calls JSON；remaining_budget JSON；last_message_ordinal int；cancel_requested bool；lease_owner UUID；heartbeat_at；revision int |
| agent_tool_calls | id UUID PK；workspace_id FK CASCADE；turn_id FK；provider_call_id varchar；tool_name/version；arguments JSON；arguments_hash；effect；status；result_artifact_id nullable FK SET NULL；operation_ref nullable；attempt int；started_at/completed_at；error JSON；UNIQUE(turn_id,provider_call_id) |
| agent_artifacts | id UUID PK；workspace_id FK CASCADE；kind QUERY/ROUTES/MATERIAL/PAGE/REPORT/PRESENTATION/NOTE/IMPORT；payload JSON；content_hash；source_refs JSON；created_by_call_id nullable；created_at/expires_at；index(workspace_id,kind,created_at) |
| agent_operation_receipts | id UUID PK；owner_key；idempotency_key；operation_kind；payload_hash；status APPLIED/NOOP；entity_kind/entity_id；before/after JSON；authorization_snapshot JSON；created_at；UNIQUE(owner_key,idempotency_key) |

所有JSON在Postgres用JSONB、SQLite可用JSON，UTC时间。created_by_call_id可留无FK避免循环insert；若加FK须nullable+deferred或insert后更新。artifact ref格式`artifact:<UUID>`，knowledge ref格式`program:<UUID>`/`tier:<UUID>`/`activity:<UUID>@<versionUUID>`；route/step在ROUTES artifact中`artifact:<UUID>#route:<local_id>`，服务端解析作用域和版本，不依赖短引用隐藏表。UI收到server生成URL，不把ref直接插为HTML。

Checkpoint phase只允许 READY_MODEL/MODEL_RUNNING/TOOLS_PENDING/TOOLS_RUNNING/FINALIZING/COMPLETED/PARTIAL/CANCELED/FAILED。没有业务状态。tool status PENDING/RUNNING/SUCCEEDED/FAILED/CANCELED。FAILED结果仍返回模型，run不一定FAILED。

保留24小时会话TTL及级联清理临时产物、工具日志、消息和事件；heartbeat不无限续期，固定expires_at。operation_receipts是用户操作回执，不能随工作区过期删除；authorization_snapshot保留相关用户原话片段、message id、时间和请求hash，不复制全部聊天。raw网页最多1MB每artifact；超出截断并保留链接/截断位置，不能默默标完整。

## 3. 上下文构建

默认单次输入目标24k tokens，硬限制`min(32k,provider.context_window-reserved_output-1024)`；不确定context_window要求配置。工具定义通常应低于8k；定义超预算启动/注册失败，不按用户关键词隐藏工具。全部12项工具始终可发现。

入模顺序：系统角色及工具说明 → 当前笔记（最多2k tokens，标明model-authored）→ 最新焦点及展示摘要（最多1k）→ 最近对话与本轮未完成的完整tool-call/result配对 → 本轮相关结果摘要 → 最新用户输入。最新用户消息只出现一次，不能因重复插入变成两个用户事件。

超预算依次：完整历史移至workspace.read索引；旧工具结果换成摘要及artifact引用；保持最近用户消息、仍适用授权引用和本轮工具调用配对不可拆。默认最近12条用户消息/完整回答只是初始窗口，不是永久丢弃边界；带工具调用的进度正文和工具结果不另占对话条数，但仍随完整调用配对保留并计入token预算。每次暴露`history_available_before`和可读cursor。焦点是用户实际点击对象；若没有点击不造focus。

无需每轮额外摘要模型。模型可调用workspace.note维护≤8000chars任务笔记；未维护时仍以历史索引找回。压缩只移出内容，不由规则重新解释用户条件。笔记无论写“目标锁定”等字样都只是可修正上下文，不能成为执行权限。

审查修订：撤回已结束轮次的last_metadata聚合和仅名称/路径索引压缩。在窗口内保留原始工具调用/结果配对、资格未知、来源版本和实际展示顺序；超整体预算按完整旧turn移出并提供历史入口。不得在通用context中识别effective_query或推导最新任务条件。后续工具摘要需先定义并验证保真契约，不以节约token为理由丢弃证据。

路线分页快照必须显式存储route_order列表；游标只索引该列表。PostgreSQL JSONB不保证对象键的插入顺序，不得通过routes字典键顺序定位下一页。新快照从第一页到续页保持同一候选顺序，旧无顺序字段快照采用稳定排序。物料按原始规则章节匹配后分页，不得先切碎再按名称过滤导致同条规则的费用/限制丢失。

独立tool/result参数及provider日志不复制到自然聊天正文。所有context摘要保留status、scope、version、unknown和完整结果ref；不能只保留候选名称丢失资格限制。trace分别记录实际输入bytes和provider真实token，不把估算当真实。

## 4. 会籍保存和目录缺失

StatusHolding已经有显示名、nullable program/tier IDs、revision、identity_status，可复用，不需新平行会籍表。

- 唯一绑定：identity_status=CONFIRMED（表示目录身份解析完成，不代表申请资格已核实），显示名从目录取，保存用户原话在操作回执。
- 用户明确授权保存且给出了项目和等级，但目录缺失：program_id/tier_id可null，identity_status=NEEDS_CONFIRMATION；program/tier显示名保存用户明确词，不猜更高级别。返回“已保存原始会籍，目录等级未对应”的状态供模型解释。
- 只有“金卡”无项目不得创建一个无归属持有会籍；返回INVALID_ARGUMENT/MISSING_PROGRAM，仍由模型决定后续。
- 已解析program_key沿用现有规范key；未解析为`unresolved:`+canonical(program_name)，只做文本归一，后续关联目录由模型明确更新，工具不偷偷合并。
- 同program_key同tier/valid_until重复create返回NOOP；同project已有不同等级的create返回CONFLICT带existing ref/revision，模型据用户意图调用update，不能create静默覆盖。
- update/delete锁record并检查expected_revision；字段未给不改，null清空。delete回执保留before，后续用户授权可用create恢复，恢复仍检查当前冲突。
- 目录身份缺失的用户会籍不阻碍Agent解释常识。路线使用未解析会籍时返回缺口；不得将其自动丢弃后声称全部会籍已考虑。

这不是允许模型自动写知识库：只有StatusHolding和用户操作journal可写，MembershipAlias/Program/Tier不由该工具写入。

## 5. 写入幂等与原子性

在同一个数据库事务内：检查authorization引用与幂等key → 查询已存在receipt → 锁holding/goal与revision → 执行变更 → UserBusinessOperation既有journal记录 → 插入APPLIED/NOOP receipt → commit。rollback必须全部失败，receipt不会先于真实变更提交。

重复key且payload_hash一致直接返回原receipt；不同payload为CONFLICT。不能依靠模型自己保证不重试。重复的新call_id调用同一create，由自然主键及NOOP进一步避免重复记录。receipt中的before/after与journal一致；实体revision在实际变化时+1，NOOP不增加。

临时tool_call intent先入库，USER_WRITE事务在业务服务内部原子完成；若写成功但tool_result尚未记录，恢复通过operation_key找到receipt重建结果。READ与WORKSPACE_WRITE可以安全重试，但display.present用call_id生成固定presentation操作key，避免重复卡。

## 6. 中断与恢复

SSE断开不取消run；客户端按event sequence续订。显式cancel标cancel_requested并通知工作者。lease过期后恢复工作者先锁run revision：
- completed调用复用result，不再执行；
- pending调用按原参数执行；
- running USER_WRITE先查receipt，不盲目重发；
- 未完成模型流已输出文本保留并标interrupted，未完成arguments不执行；追加一次runtime_interruption给下一模型，已有tool receipts带回。

恢复不把部分文本拼接成同一个已完成消息：创建新的assistant message id，前段保留interrupted标记。所有事件seq唯一递增，客户端按seq去重。模型超时无已执行动作可有限重试一次；再失败给真实错误。取消/硬budget/失去lease后旧worker不得执行新调用，提交结果须校验lease owner/revision。

## 7. 工作流隔离验证

Agent读取端口通过独立只读session执行，Postgres transaction read only；写工具使用单独UserMemoryPort并限制允许表。SQLite用repository接口测试写入范围，不声称具备DB角色隔离。Workflow保留自身Session与UserBusinessOperation既有迁移机制，不因为Agent新工具更改采集或发布开关。


### 用户确认的优先级（2026-09-08）

效果与回答正确性优先于上下文效率。任何压缩不得以丢失用户条件、遗漏必要证据、减少应执行操作或降低回答质量为代价；发现退化时撤回对应压缩。先通过真实语义与操作验收，再对通过的同类任务比较累计 token、调用数和耗时。失败任务即使更省 token，也不计为优化达标；不能为追求压缩比例放宽验收标准。


### 系统侧人工复验后的投影收口

activity evidence 仅投影请求方面的事实、适用条件及版本，原始来源通过独立 section 引用展开，不重复整个活动详情与映射。资料内容搜索忽略引用 ID，按带身份/版本的细分事实或完整来源分页。长来源保留未读部分的 cursor，不能把命中片段当成已读完整条款。等待任务列表分页；旧 pending 结果通过 artifact 保留，新结果仅存相关步骤，更新/取消清空旧结果标识及签名。

本轮无法无损放入模型窗口时返回明确 CONTEXT_CAPACITY/PARTIAL；不丢弃正在执行的调用配对，也不通过额外模型摘要改写条件。
