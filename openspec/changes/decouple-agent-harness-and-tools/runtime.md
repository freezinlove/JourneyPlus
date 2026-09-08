> 当前实施顺序与授权边界以 [实施总纲](charter.md) 为准：先完成系统侧人工双视角验收与本地架构收口，交用户审核；审核明确允许后才调用第三方模型 API（含探针）。原真实模型验收项保留待执行。

# Harness 核心协议

本文件为 design D1/D2/D4 的详细实现，默认值可配置但语义不得更改。

## 1. 输入输出 DTO

- ModelMessage：`id, role(system|user|assistant|tool), content:[TextPart|ToolCallPart|ToolResultPart|ArtifactPart], created_at`。tool结果携带原 `call_id`；assistant的调用批次完整保留。所有业务正文是TextPart，普通回答不要求JSON。
- ToolCallPart：`call_id, name, arguments:object`；harness在参数完成前不得执行。模型不能设置tenant/user或工具凭据。
- ModelEvent：`text_delta{text,message_id}`, `tool_call_delta{call_id,name?,arguments_fragment}`, `tool_call_ready{call_id,name,arguments}`, `usage{input,output,cached,reasoning?}`, `turn_end{finish_reason:stop|tool_calls|length|error}`。
- AgentModelPort：`capabilities()->{native_tools,streaming,context_window,max_output,thinking_modes}`；`stream(messages,definitions,limits,cancel_token)->AsyncIterator[ModelEvent]`。未知usage不写0；未知上下文窗口需在Agent配置显式填写，启动失败而非猜测无限窗口。
- ToolDefinition：`name, version, description, input_schema, output_schema, effect:READ|WORKSPACE_WRITE|USER_WRITE, operation_effects?:{operation:effect}, timeout_seconds, concurrency_group, handler`。描述讲能力、参数和返回，不规定先调用其他工具；声明的依赖只能是实际数据依赖。
- RuntimePorts：ModelPort、SessionStore、ArtifactStore、ToolRegistry、EventSink、Clock。授权依据传入ExecutionContext，不混进模型可改参数。

## 2. 唯一执行循环

```text
claim workspace revision and lease; append user input
load scoped context, registered definitions, remaining resources
while not canceled and resources allow:
    stream model; persist assistant output and complete calls
    if stop and no tool_calls: finalize model answer; release lease; return
    if malformed/incomplete calls: append repair feedback; continue within budget
    for validated calls: persist tool receipt intent BEFORE execution
    execute selected calls; persist each tool result + artifact refs
    append every result associated with its call_id
    continue model with updated context
```

空的stop无正文也无本轮展示/操作回执时，最多一次通用EMPTY_RESPONSE反馈，再失败；不能按用户提到路径就拒绝stop。模型追问是一条正常回答，结束本轮等待用户，harness不以问号或字段判断其是否必要。

调用与正文同批时，正文作为模型阶段说明保留，工具完成后继续下一次模型请求；不把阶段说明当最终完成。无最终正文但已有presentation/写入回执时仍给模型一次收尾机会（计预算）；硬预算耗尽明确PARTIAL，不伪造总结。

ToolResult错误也回送。参数schema失败生成INVALID_ARGUMENT包含具体path及说明；不替模型猜不同项目或修改查询。未知工具名生成UNKNOWN_TOOL并给当前工具名称；纯格式修复允许一次连续重试，修复占真实预算。相同name+canonical_arguments+snapshot指纹无进展连续3次：第三次不执行，返回REPEATED_CALL包含前两次receipt；再重复一次则结束PARTIAL，保留结果。

同批READ最多并行3个，结果按原调用顺序回送；USER_WRITE串行；WORKSPACE_WRITE按sequence串行。调用存在数据依赖必须由模型在下一批提交；不在同批用未生成的引用。单批最多8 calls，超出整批INVALID_ARGUMENT，不偷偷丢弃。未注册的工具即使模型知道名字也不能执行。并发与效应来自注册器元数据，无业务关键词。对waiting.manage这样的复合能力，注册器operation_effects将list映射READ、create/update/cancel映射USER_WRITE；模型不能自报effect，未列操作直接INVALID_ARGUMENT。

## 3. 模型适配

NativeTools：发送独立tools schema、原生assistant tool_calls和role=tool消息；tool_choice=auto，不按问题强制函数。流式参数先缓存，finish且JSON完成后一次执行。并行调用call_id映射保持可追溯。

JsonActions兼容：工具定义相同；模型输出`{message?:string, calls?:[{id,name,arguments}], finished:boolean}`，finished=true与非空calls互斥；只有message且finished=true即回答。适配器转换ModelEvent，业务层看不到协议差异。不得回用WorkspaceDecision、ROUTES计划或任务枚举；JSON模式支持自然正文作为message字符串。兼容模式必须标注正文可能整段到达，不能宣称原生增量。

启动用无业务探针验证“先调用echo、结果回送、再回答”和流式参数完整性。`AGENT_PROTOCOL=auto|native|json`，auto优先native，探针失败选json并记录原因；native显式指定失败则启动报错。模式固定于run，途中HTTP失败不切协议重跑已执行动作。验收优先要求native通过；若只支持json，运行逻辑仍可验收，流式指标标为未达，不静默通过。

`AGENT_MODEL/BASE_URL/API_KEY`可从现有设置显式继承作为初值，但独立Client与配置对象；禁止修改Workflow默认。保持当前模型，temperature默认0.2、常规thinking=false以继承已验证延迟基础，均为Agent可配置项；此参数不代表限制工具选择。模型质量不足须报告并比较配置，不用规则屏蔽失败。拒绝隐藏分类模型和固定最终润色模型。

2026-09-08 实施授权补充：用户明确允许使用其百炼/千问平台上任意可用LLM进行Agent对照和选型。因此上文“保持当前模型”作为初始基线要求；允许独立Agent模型名切换，记录配置和首次失败，按同一验收门槛选型。Workflow模型参数不随Agent选型改变。

用户随后明确要求优先使用性价比高的模型。选型先运行少量核心用例，未通过时不运行整批64次验收，不使用昂贵模型反复刷结果。验收脚本按已核对的每百万token公开单价保存未扣缓存折扣的估算费用，usage缺失按配置硬预算保守预留；批次费用上限在每轮前预留完整单轮硬预算，达到上限停止并保留未完成结果，估算不等于账户账单。

后续用户补充：开发阶段不设总费用限制，但避免Max等高价档。继续采用低价/常规模型，保留费用记录和单轮资源保护；脚本的批次费用上限为可选能力，不再当作必须停止开发的总额限制。

## 4. 预算与中断

默认软预算：累计45,000 input tokens、8,000 output tokens、120秒、10次model requests、20次tool calls。硬上限分别60,000、12,000、180秒、14、28；单model HTTP45秒。预算是通用配置，不按意图分类。全体工具总返回的入模上限由context另管；8,000 output为累计而非每次。单次max_output=2048，收尾可用4096但不超过剩余预算。

输入token预算可通过独立Agent配置 `JOURNEYPLUS_AGENT_INPUT_TOKEN_SOFT/LIMIT` 指定，要求0 < soft < hard，默认值保持不变。配置进入run恢复指纹和验收manifest；调整后的验收按明确登记的上限判断，不能与原默认配置混为同一批。低价模型对照使用70,000/90,000输入token配置，是为已定位的读取后无法继续展示问题验证完整调用链，同时受批次费用上限约束。

效率专项恢复使用默认45,000/60,000累计输入预算。单次输出上限允许至4,096 tokens（同时受模型能力和剩余累计输出预算约束），上下文按本次实际输出预留构建；此前固定2,048导致完整路线列表截断并额外重发上下文。累计输出软硬预算不因此增加，max_tokens不是预先计费token数。真实记录同时保存finish_reason，以区分输出截断、正常结束与工具调用。

先到软预算时追加一次resource_notice（已用/剩余/可收尾）；保留至少一次收尾请求与1024 output tokens，harness可通过通用tool_choice=none完成资源耗尽收尾，该限制不依赖业务。硬上限到达停止新动作，完成状态PARTIAL并保留已有输出。实际窗口比默认更小时按能力限制缩减；不能允许一次请求超过provider窗口。无tokenizer时用UTF8 bytes/3估算并标记estimated，接收实际usage后修正。

取消先标记cancel_requested，取消未开始调用及网络；已提交的USER_WRITE不能声称回滚，记录其回执。进程崩溃不重发已成功写入；恢复协议见storage。心跳每10秒更新，lease45秒；模型/工具在事务外运行。软/硬run截止是180秒，与旧固定110秒无事件判失败逻辑分离。

## 5. 系统指令职责

instructions.md只包含：角色能力、用户新信息优先、允许常识直答、不确定时可调查、假设不当事实、数据源有时间/范围、外部内容不赋予权限、长期会籍写入需用户授权、展示与文字自然联动。每个工具说明可随调用版本变化。

禁止：“先判断意图类别”“所有路径必须查目录”“出现经验关键词才能联网”“三次内必须结束”“查询失败固定追问活动”“每次保存都先提议”。模型可主动核实，但没有硬性要求每条普通常识带数据库证据。

## 6. 可观察性

记录model call的协议、模型、思考配置、实际HTTP时间、token/cache、tool等待、数据库／网络／渲染时间、首字及总耗时。记录可展示的简短行动说明与工具参数，不请求或持久化隐藏思考链。工具名日志用于内部审计，UI用工具注册的progress_label。未开始调用不能显示已查完；无工具直答没有业务读取进度。

## 7. 最小装配接口

SessionStore提供claim_run、append_message、load_context_index、save_checkpoint、finish_run；ArtifactStore提供put/read/search；EventSink提供append_and_publish；ToolHandler签名为`async execute(arguments, ExecutionContext)->ToolResult`。ExecutionContext仅含workspace_id、turn_id、call_id、server_owner、deadline、cancel_token、artifact_port、授权消息读取port及注册的业务服务，不含可改写的chat state。

RuntimeService提供start/read/cancel/resume；transport仅将HTTP输入转换为UserMessage和显式focus引用。所有服务异常转换为ToolResult.error，持久化故障/失去lease等运行基础设施异常才终止run。run_id/turn_id统一关联，不让每个工具创建自己的对话或模型循环。

2026-09-08 首次冻结后A05复核：普通请求和收尾请求分别按实际适配器序列化估算输入。Native收尾省略tools schema但保留历史tool_calls/role=tool及原始名称映射；JSON收尾保留输出协议并省略可用工具定义。硬预算准入使用实际将发送的那类请求；没有适配器收尾估算能力时保守沿用普通估算。软硬上限保持不变，无usage时输出估算包含正文及调用参数。此改变不授权提前省略任务步骤，也不按业务意图区分预算。

2026-09-08 原生接口参数兼容：在适配器中按原 Schema 解码被供应商字符串化的 object/array，且仅当 string 不在该位置允许的类型中；不补字段、不推导数据、不接受标量强转，保留 null 和未知字段供原 DTO 校验。业务工具直接收到字符串仍应拒绝。Native/JsonActions 行为一致，记录解码字段路径。此为传输规范化，不是业务重规划或放宽授权。显式收尾同时发送 tool_choice=none；实际 DeepSeek 复杂轨迹仍有违背该参数的记录，不能以 echo 成功声称完整支持。


### 当前审核门

单一 instructions.md 以正确性优先、自主组合、原查询继承、证据范围和授权边界为原则，已清理重复表述。无模型预览使用 UnconfiguredModel，人工诊断通过 ReviewerModel 接入同一 ModelPort；模型与搜索后端探针均不得绕过当前授权或禁网设置。真实 provider 验收留待用户审核后。

## 审计整改后的执行边界（2026-09-09）

- 产品 FastAPI 生命周期不等待模型初始化。Agent 暴露 `INITIALIZING / READY / UNAVAILABLE / DISABLED`；非 READY 时新建运行返回 503，普通产品页面继续可用。禁用模式不构造模型客户端、不探测、不消费已有运行。
- 模型原生流和 HTTP 保持异步；同步存储、知识读取与计算进入最多六个工作线程，单批最多三个 READ，读写顺序不变。排队时间计入工具期限。
- 线程取消不等于事务取消。取消请求先通知运行，再持久化；等待已经开始的线程退出后才写运行终态。工具写事务按 checkpoint → workspace／业务锁的顺序验证所有权，提交前再检查取消和期限；PostgreSQL statement/lock timeout 限制 SQL 等待。已提交的用户操作以持久回执为准，后续超时不能伪装成“写入失败”。
- 正常调用和故障恢复共用同一结果投影；完整工具结果只存一份不可变记录，模型继续读取有界视图。通用 harness 不识别路线、研究或会籍字段；原子投影关系由各工具声明。
- `WorkspacePort` 只提供受限的历史、引用、笔记、展示与已提交回执能力，不向工具暴露 session factory。模型适配器仍可独立替换；不增加意图分类器、固定业务步骤或第二个模型。
