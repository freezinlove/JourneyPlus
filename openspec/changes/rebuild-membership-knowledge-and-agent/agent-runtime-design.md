# 对话、工作区、确认与等待运行设计

对应 D7/D8/D12/D13。保留单 Agent、现有 AIProvider 和同步有界回合；不建设多 Agent、异步 Run 平台。以下状态与契约是实施基准。

## 1. 动作契约

模型输出 envelope={schema_version:1,action,payload}，action 判别联合如下。理解草稿不强制 target；Schema 合法后再执行动作级语义与权限验证。

| action | payload | 服务端行为 |
|---|---|---|
| ANSWER | text、blocks[]、next_steps[]、claim_refs[] | 校验引用／块类型后组装可信展示；可以纯文本闲聊 |
| ASK | question、reason、choices[] | 每回合最多一个关键问题，保留草稿，回答后继续同工作区 |
| READ | requests[{tool,args}] | 调用受限读取工具；最多 3 个有依赖顺序的请求，不开放任意函数名 |
| PROPOSE | kind:HOLDING_SAVE/HOLDING_EDIT/QUERY_ADJUST/WAIT_CREATE/WAIT_CONTINUE、changes、reason、support_refs | 创建待确认动作，仅 proposal 无正式写入；调整不能绕过硬事实 |

READ 内允许 query_activity_materials、query_membership_routes、research_statusmatcher；如果后一个依赖前一个定位结果，可用前一请求已返回的唯一 ref，歧义直接中止后续并向用户澄清。一个回合共享所有预算，重复 READ 不能重置外部额度。模型不得输出“执行确认”动作；确认由用户消息或专用确认端点产生。

任意输入处理矩阵：闲聊→ANSWER，无业务读取；活动细节→活动资料；可达探索→路径，无目标合法；复合问题→受限组合；指代→工作区定位；新增会籍→临时理解+PROPOSE；无能力话题→说明现有能力并正常结束，不抛业务 Schema 错误。

## 2. 回合执行状态

Turn 状态 RECEIVED → THINKING → READING → THINKING → ASSEMBLING → COMPLETED；可在任一步进入 FAILED_RECOVERABLE；ASK/PROPOSE 是正常 COMPLETED，但留下 pending 状态，不把工作区关闭。每回合总模型次数≤3，格式修复≤1且计入三次。

整回合初始总截止时间90秒（可校准，包含模型、工具和组装），每次外部调用 timeout 不超过剩余时间；StatusMatcher 的20秒子预算仍受总截止限制。超时返回已有确定事实和可恢复错误，不继续后台无界运行。第三次模型仍请求 READ 时不执行新的模型循环，返回已有数据、未完成方面和续接建议。

处理顺序：校验幂等键和工作区有效期 → 原子占用回合 revision → 保存用户消息与最小草稿 → 释放事务 → 模型／工具 → 校验并组装 → 原子写结果、展示顺序及 revision。读取不持有长数据库锁；并发消息采用单工作区单进行中 turn，第二条返回 409 TURN_IN_PROGRESS 及可重试信息，不丢输入。服务崩溃后过期执行租约标 FAILED_RECOVERABLE，不自动重发可能涉及确认的动作。

输出 JSON 失败／Schema 格式失败可以修一次，修复输入是脱敏错误路径、原输出和原事实引用；工具不可用或事实未知不能靠格式修复改变。若已用完三次，程序直接渲染已校验数据和恢复信息，不再请求模型“总结”。Provider 不支持严格 Schema 时用 JSON object 输出加服务端验证；拒绝未知动作、额外字段及越权引用。

错误码固定 CONFIG_UNAVAILABLE/PROVIDER_TIMEOUT/PROVIDER_HTTP/INVALID_JSON/SCHEMA_ERROR/INVALID_ACTION/TOOL_ERROR/BUDGET_EXHAUSTED/WORKSPACE_EXPIRED。响应保留 run_ref、可读原因、retryable、已取得的内容块；日志只记必要脱敏字段，不把所有错误合成“未结构化”。模型 text 不能声称工具已执行，依据区由真实调用记录生成。

## 3. 临时工作区存储合约

复用 agent_interactions 作为 workspace 表（类可更名），增加 revision:int、active_turn_id?:UUID、lease_expires_at?:timestamptz；status 仅 ACTIVE/EXPIRED。created_at 起默认 24h 固定 expires_at，消息和点击不续命。state JSONB schema_version=1：

```text
state
  query_draft: RouteQuery + field_origins（USER/CONFIRMED/HYPOTHESIS）
  focus: {kind,ref,presentation_id,updated_at} | null
  snapshots: {snapshot_ref: {activity_version_ids,holdings_revision,query_hash}}
  references: {short_ref: {kind,stable_id,version_id,snapshot_ref,label}}
  presentations: [{id,turn_id,ordered_route_refs,block_refs}]
  pending_action: {id,kind,base_revision,base_holdings_revision,payload,expires_at} | null
  research: {cache_key: ResearchObservation}
  unresolved_question: {text,field,subject_ref} | null
```

新增 agent_workspace_messages(id,workspace_id FK CASCADE,turn_id,ordinal,role:USER/ASSISTANT,content JSONB,created_at)，unique(workspace_id,turn_id,role,ordinal)。content 保存用户可见文本与结构块，图和资料只存版本引用及必要显示快照，不保存思考或来源全文。读取 UI 用此表，模型只取最近窗口和必要状态。

新增 agent_turns(id,workspace_id FK CASCADE,client_message_id,request_hash,status,input_revision,result_revision?,model_calls,repair_calls,error_code?,started_at,completed_at?)，unique(workspace_id,client_message_id)。相同键同请求返回已有结果；相同键不同请求 409。过期后消息、turn、state/research 级联清除；精简诊断若保留不能恢复聊天正文。WaitGoal.source_interaction_id SET NULL，不级联删除业务任务。

工作区短引用终生不改绑；相同路线在新快照用新 ref，可共享稳定名称但需版本提示。序号来自用户所指的上一展示 presentation，不是本轮查询排序。显式“路线 A”优先于最近点击 B；多对象“它”不能唯一定位则澄清。切换话题只保留可恢复会话，不把无关候选塞入下一模型包。

## 4. 确认规则

pending_action 同时最多一项，新提案明确替代旧提案；有效期 min(创建后15分钟,workspace.expires_at)。绑定 revision 与 holdings_revision，确认前重新检查相关事实快照和条件。展示具体会籍或调整前后与依据，用户明确确认后才提交。

专用确认请求 {pending_action_id,expected_revision,client_action_id,decision:CONFIRM/REJECT}；自由文本“确认”仅在上下文只有一个未过期动作且用户未同时修改内容时转换到同一处理器。模糊“好吧”不跨多项猜确认。条件修改先生成新 proposal，不复用旧确认。

HOLDING_SAVE/EDIT：唯一识别项目等级，单事务写规范会籍、递增 holding revision、消费 pending，记录业务幂等键。临时目标和来源取得方式不保存到 holding。QUERY_ADJUST：仅更改当前查询，没有用户同意不适用建议；REJECT 清除 proposal，不主动递归放宽其他条件。快照过期需重新评估，发生实质变化重新展示而非悄悄写入。

## 5. API 划分

新增 `/v2`，旧 `/v1` 在兼容期保持旧语义并有迁移说明，不能静默改义。路由名可以调整，但端点职责及调用边界固定。

| 端点 | 输入／输出和副作用 |
|---|---|
| POST /v2/agent/workspaces | 创建 ACTIVE 工作区，返回 id/revision/expires_at；零模型 |
| POST /v2/agent/workspaces/{id}/messages | text、client_message_id、expected_revision、optional subject_refs；运行正常 Agent 回合，返回 presentation/basis/pending |
| GET /v2/agent/workspaces/{id} | 分页会话、最新状态、pending；无模型、无通知消费 |
| POST /v2/agent/workspaces/{id}/focus | ref、presentation_id、expected_revision；仅更新浏览焦点，零模型、零调查 |
| POST /v2/agent/workspaces/{id}/confirm | 确认第 4 节 pending；业务幂等，必要后续查询走显式回合 |
| GET /v2/activities/{id} 与 /materials | 可带 version_ref/view/cursor，确定性活动详情／证据 |
| POST /v2/routes/query | 查询结构条件或展开 refs，确定性图与路径，不运行 Agent |
| GET /v2/wait-goal | 返回业务任务／待展示结果，零消费 |
| POST /v2/wait-goal/{id}/seen | result_id、idempotency_key，确认实际展示，零模型 |

普通浏览允许用户主动打开原始来源链接；这不是 Agent 在后台执行 StatusMatcher 调研，也不绕过自动读取授权。

## 6. 等待任务状态机

复用 agent_wait_goals，新增 revision:int、holding_snapshot:JSONB、conditions_schema_version:int、last_checked_snapshot?:text、result_id?:UUID、result_version?:int、ended_at?:timestamptz。query 只保存确认条件，preferences 仅属于本任务，不能成为以后默认画像。holding_snapshot 固定建任务时的会籍 ID、等级、有效期和 revision。

状态：ACTIVE → RESULT_PENDING → COMPLETED；ACTIVE → NEEDS_RECONFIRMATION（持有会籍实质改变）或 CANCELLED；RESULT_PENDING 可以由明确 WAIT_CONTINUE 产生新的等待轮次 ACTIVE。用单用户业务锁保证 ACTIVE/RESULT_PENDING/NEEDS_RECONFIRMATION 中合计最多一个任务，而不是仅各状态一个。

每日检查先核对 holdings revision；会籍变更不默默使用旧等级发推荐，也不默默放宽任务，进入 NEEDS_RECONFIRMATION 并只给一次确定性状态提示。会籍自然到期会移除无效起点并显示原因。用户确认新起点后恢复。

ACTIVE 检查流程：取得发布快照 → 按 query 确定性找正式新匹配 → 无命中保存检查标记（零模型／零通知） → 有命中保留 candidate refs 和版本 → 必要时受限生成回答 → 原子写唯一 result_id 并进入 RESULT_PENDING。生成失败保持待重试而非已通知；同一快照／结果语义幂等，不因列表顺序变化再次创建。

RESULT_PENDING 不再搜索更优；GET 可以重复返回。前端实际呈现后 POST seen 幂等变 COMPLETED。用户关闭页面或渲染失败不消费。若用户明确继续，开启新轮次并保存已展示候选语义集合，仅新方案或实质变化才再命中。保持一个任务身份和递增轮次，不创建多任务。

研究偏好在建任务时需明确，执行时仍检查服务授权；经验不可用不能阻止官方事实的已知匹配呈现，说明未调查。没有近似方案也可提供等待；partial 和 UNKNOWN 只能表述“当前范围未找到”，不可作为证明全库无解。

## 7. 实现落点和验收

agent/contracts.py 承载动作／响应 Schema；controller.py 处理有界回合与确认；prompts.py 消费薄数据；waiting.py 实现任务生命周期；product/api.py 区分浏览与对话；新增 workspace 服务集中幂等和 TTL。模型与持久化事务分离，不把状态机散到页面按钮处理里。

必须演练：任意闲聊无资料注入；无目标探索；先问条款再问“它”；推荐后“第二条”；点击不增加消息／模型次数；三次预算含修复；确认后网络断开重试不重复写；两个标签页并发；24h到期；等待命中但未展示、重复 seen、会籍变更及继续等待。
