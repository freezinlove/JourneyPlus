> 当前实施顺序与授权边界以 [实施总纲](charter.md) 为准：先完成系统侧人工双视角验收与本地架构收口，交用户审核；审核明确允许后才调用第三方模型 API（含探针）。原真实模型验收项保留待执行。

## Context

本 change 是 2026-09-08 讨论的实施设计。当前 `/workspace` 通过 knowledge_api 创建 WorkspaceService；workspace.py 同时承载语义路由、模型协议、工具、状态、写入和展示。task_context/completion/display_focus/research_intent 等读取原话决定动作；turn_planning 将路径绑定 PLAN→目录→RESOLVE；构造函数将调用数裁到 3；narration 将程序简报改写成正文；同进程还有 v1 AgentController。旧方案强调减少调用与防错误，但把模型的任务判断变成程序责任。

讨论依据与旧需求替代见 [supersession.md](supersession.md)。本目录所有设计附件均为规范性实施约束，不能只读 proposal 或 tasks。文件间冲突按 specs → design → 附件处理；出现实际矛盾先修设计记录，不自行退回旧固定流程。

## Goals / Non-Goals

**Goals:** 单模型具有理解、常识运用、规划、工具选择、纠错、追问、推荐和回答权；harness 通用且业务无关；工具可独立组合；上下文有界但可找回；会籍保存可靠；程序忠实执行及展示；Agent 和 Workflow 可分别修改、测试和启动。

**Non-Goals:** 不修改新闻采集／提取／发布流程及 Workflow 模型参数；不重做其简报和完整关系图；不全量建设全球名称库；不引入多 Agent 编排、任意 shell/SQL 执行、浏览器代申请或自动购买；不在本 change 发布生产。AI Workflow 可以是固定流程，Agent 核心不能因此成为固定流程。

## Decisions

### D1 模型持续掌握下一步

只允许通用 loop：messages + tools → model events → execute selected tools → append tool results → model。模型可零工具回答、一次调用多个独立读工具、多次调查、直接追问；不强制模型生成计划。消息类型与状态机只描述运行生命周期，不出现 ROUTES/CHAT 等业务状态。移除隐藏预读、根据关键词授权查询、强制目录和程序自行收尾。提示词不重建固定顺序。

理由：固定阶段降低部分样例出错率，却无法覆盖开放对话。选择单一 loop，拒绝在旧 workflow 上再加总分类器或审稿模型。

### D2 通用核心依赖倒置

落地目录如下（精确责任；小 DTO 可同文件，不为每个类型生成空包）：

```text
src/journeyplus/agent/
  harness/
    contracts.py      # ModelMessage/Event, ToolDefinition/Result, RuntimePorts
    runtime.py        # 单一循环，取消，结果回送
    registry.py       # schema/版本/执行器注册，不理解会籍
    context.py        # 上下文投影、预算和历史索引
    budget.py         # 资源及重复调用上限
  adapters/
    model.py          # Agent 独有 NativeTools + JsonActions 适配
    persistence.py    # 会话、工具日志、产物、checkpoint
    transport.py      # SSE/HTTP事件映射
  tools/
    contracts.py      # 下文所有业务工具schema
    knowledge.py      # 活动与目录读取
    routes.py         # 独立路线输入和结果，无chat状态
    holdings.py       # 授权会籍操作
    research.py       # 搜索/读页面/解析报告
    workspace.py      # history/artifact/notes
    presentation.py   # 模型选择转渲染及回执
    waiting.py        # 显式等待操作
  services/
    identities.py    # 名称/引用关联，不调用模型、不生成追问
    presentations.py # 纯构建器及版本链接
    research.py      # 网络/报告适配，复用解析器
    user_memory.py   # 用户写入事务与journal
  composition.py     # 注册工具、构造ports和实例，唯一装配点
  instructions.md    # 单一角色/证据/记忆/工具使用原则
src/journeyplus/product/agent_api.py  # v3薄路由
```

harness 只依赖标准库、类型校验和自己的 ports；禁止导入 knowledge、membership、product、SQLAlchemy、WorkspaceService 或旧 controller；禁止出现项目名称对照/用户话术正则。tools 不导入 runtime 或旧 workspace；services 不接受整个聊天 state，不读取 current_question。adapters/persistence 可以依赖 SQLAlchemy。composition 依赖各层，其余层不得反向依赖它。避免把 1300 行控制器移动到另一个大文件；单模块超 400 非空行须在代码评审说明责任是否单一，不以行数代替设计。

### D3 业务能力作为工具，名称目录可选

完整契约见 [tools.md](tools.md)。不将全部函数暴露：初始注册 12 个工具，按独立能力组织，而非按必须顺序组织。底层使用已有只读知识服务和确定性路线算法；输入必须足够明确或返回缺口；工具不猜用户下一步、不替模型发问。身份名称可直接传业务工具，原始数据库 UUID不需用户/模型背诵。内部绑定只定位数据，不要求模型“证明全日空就是 ANA”。未解析不会创建正式知识身份。

### D4 运行协议和参数隔离

详见 [runtime.md](runtime.md)。保留 workflow 的 AIProvider.generate_structured；新增 AgentModelPort，不能修改共用 provider 默认思考/temperature 来影响 workflow。NativeTools 与 JsonActions 使用相同语义循环，按启动能力探测选择，不在业务任务半途默默切模式。现用 deepseek-v4-flash 先验收，不预先承诺其可靠性，不默认更换服务。

### D5 共享知识，不共享业务链路

Agent 的知识端口只提供读取已发布活动／指定历史版本、目录、确定性计算和简报链接。不得调用采集、提取、发布、简报重建或完整图生成任务。图卡可复用纯渲染组件和版本对象；简报跳转是页面联动，不触发 Workflow 工作。Workflow 服务禁止反向导入 agent/harness、tools 或工作区状态。

共享数据库可继续存在：Agent 临时表、用户表与正式知识表是三个写入范围。不引入第二份活动事实库。共享工具式读取不是共享控制器。测试通过端口契约和“Workflow未启动也可用Agent”验证，而不只检查目录分开。

### D6 明确数据与记忆模型

详见 [storage-context.md](storage-context.md)。复用现有会话、消息、turn、delivery表，新增工具日志/产物/通用checkpoint和持久操作回执。StatusHolding继续作为长期会籍；目录缺失可按用户明确原话保存为未解析，不制造正式目录记录，路线计算清楚返回未解析持有会籍。任务笔记属于24小时工作区，不覆盖用户原话。

### D7 模型拥有回答与展示

详见 [presentation-api.md](presentation-api.md)。正常正文来自当前模型，自由工具结果与对话上下文；不经过 verified_route_text 的无条件覆盖，也不做基于白名单数字的删句。价格、资格、版本和引用等结构化展示字段由工具保证。模型决定卡图对象顺序，渲染器不重排、不添加推荐理由。点击打开简报是无模型 UI 行为，点击后的语言解释交模型。

### D8 替换与兼容有界

详见 [migration.md](migration.md)。独立 v3 与 runtime配置隔离验证，旧对话只读保留，显式导入到新会话，不自动迁移旧控制标记。最终 v1/v2写入口退役为可识别错误，不能长期运行两套决策器；普通活动/完整图/简报路由不受影响。

## Risks / Trade-offs

- 自主性增加不保证模型正确 → 用结果和工具轨迹做真实评测，不靠话术补丁覆盖能力缺陷。
- 多轮调用可能更慢 → 保留缓存、批量独立读、按需展开、可取消和明确资源预算，不重新固定三步。
- 自动允许明确授权写入 → 用户原话引用、幂等操作和版本校验；未授权不执行，确认只用于实际授权缺口，不每次固定确认。
- 不静默覆盖正文可能暴露模型事实错误 → 以清晰证据输入、工具计算及最终评测把关；不宣称能数学证明所有自然语言。必要时模型自行核实，不能由后台改成另一结论。
- 网络能力不齐 → 明确内置站点发现与可选搜索后端边界，缺能力返回UNAVAILABLE，不假装全网搜索。
- 暂时并行新旧 API → 只在隔离验证阶段保留，任务清单包含退出节点。

## Migration Plan

依次完成模块与契约、模型协议、日志循环、只读能力、记忆写入、网络与展示、前端与API、真实验收、切换清理。此顺序是实施依赖，不是模型执行步骤。新增迁移保持旧知识和用户数据可读取，回滚只切路由/配置，不自动downgrade或删除新记录。所有生产切换保持未执行，直到另行授权。

## Open Questions

无待后续实施者决定的核心架构问题。NativeTools服务兼容性、实时网站可访问性、真实延迟是验证项；失败处理和兼容路径已定义。选择具体测试库名、迁移序号（以实施时唯一head为准）、依赖版本属于实现环境工作，不改变设计。新增通用搜索账户、扩展到真实多用户权限或生产发布不在本次默许范围。

## Implementation reading order

0. [实施总纲](charter.md)：当前阶段、架构质量要求与用户审核门。

1. 本文件与 [替代清单](supersession.md)
2. [运行协议](runtime.md) → [工具协议](tools.md)
3. [数据和上下文](storage-context.md) → [展示与API](presentation-api.md)
4. [迁移映射](migration.md) → [验收矩阵](acceptance.md)
5. specs 下六项能力及 [任务清单](tasks.md)
