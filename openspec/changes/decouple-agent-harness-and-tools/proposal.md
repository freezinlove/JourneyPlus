> 当前实施顺序与授权边界以 [实施总纲](charter.md) 为准：先完成系统侧人工双视角验收与本地架构收口，交用户审核；审核明确允许后才调用第三方模型 API（含探针）。原真实模型验收项保留待执行。

## Why

现有 Agent 将模型绑定在关键词状态更新、固定身份解析／查询阶段、三次调用预算和程序生成结论中；模型自主理解、用常识直接回答、选工具和根据结果调整任务的能力被削弱。用户确认重构为“模型 + 通用 harness + 独立业务工具”，并要求与新闻提取、知识发布、完整图及简报 AI Workflow 严格分离。

## What Changes

- **BREAKING**：以业务无关的工具调用循环替代 workspace 中的语义路由、PLAN/RESOLVE、自动查库和自动收尾；不把固定流程迁入提示词。
- 建立独立模型协议、工具注册／执行协议、持久化执行日志和预算／取消／恢复机制；JSON 兼容与原生调用遵守同一运行语义。
- 将活动读取、名称目录、路径计算、会籍记忆、工作区检索、网页读取／发现、经验解析、展示和等待任务作为独立工具；名称表可读可不读。
- 业务工具接受身份名称或真实引用；数据库关联不等于证明模型常识。身份歧义与资料缺失作为工具结果交回模型，不直接代替模型追问。
- 工作区使用消息、工具结果、可引用产物和可更新笔记，不再依赖多套范围标记控制后续行为；长期记忆限于用户会籍。
- **BREAKING**：明确授权的单项会籍写入可直接执行，取消固定 PROPOSE→再确认门；明确操作幂等、版本冲突及未解析身份的保存方式。
- 模型直接组织流式回答并选择图卡／推荐；服务端负责忠实渲染和数据一致性，不覆盖其文字或重排选择。
- 新旧 Agent 入口逐步收敛；AI Workflow 采集、提取、发布、完整图、简报不改业务链路。只共享稳定读取端口及版本化对象链接。
- 本 change 包含核心协议、模块和表设计、工具参数、迁移路径、验收矩阵及旧规则替代清单，后续实施者按文档编码。

## Capabilities

### New Capabilities

- `model-led-agent-harness`: 模型主导循环、模型适配、预算、恢复和错误反馈。
- `independent-agent-tools`: 独立工具协议、身份输入、活动／路线／网络工具。
- `agent-context-and-memory`: 工作区上下文、历史找回、用户会籍与幂等写入。
- `model-owned-presentation`: 模型选择、忠实渲染、流式消息、点击对象反馈。
- `agent-workflow-isolation`: 模块依赖、数据权限、版本链接和独立发布边界。
- `agent-harness-migration-and-evaluation`: API 迁移、旧规则退出、自治行为及真实验收。

### Modified Capabilities

无已同步的主规格作为 MODIFIED 基线；使用上述 ADDED 规格。历史 change 中被替代的具体要求见 [替代清单](supersession.md)，不改写其历史实施记录。

## Impact

涉及 src/journeyplus/agent、Agent 专用模型适配、product 的 Agent 路由和工作区前端；新增 Agent runtime 表迁移。复用 knowledge 的只读服务、用户数据 journal、现有图卡基础和 HTTP 解析。旧 workflow 继续使用现有 provider.generate_structured，参数与发布行为不因 Agent 改造改变。正式部署、全量名称库建设、多 Agent 团队及 workflow 重构均不属于本 change。
