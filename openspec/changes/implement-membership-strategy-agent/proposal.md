## Why

JourneyPlus 已具备会籍事实库、用户持有会籍、统一匹配图和每日数据工作流，但用户仍需自己把自然语言目标翻译成图查询并比较路线。现在需要补上一层真正受约束的单 Agent：让它根据用户表达和程序观察自主决定确认、查询、调研、建议调整或提出持续跟进，同时保持事实判断、正式写入和定时检查由现有确定性底座负责。

## What Changes

- 新增一个面向用户的会籍策略 Agent 页面与类型化回合 API，支持自然语言输入、一次关键追问、用户确认/修改以及结构化结果呈现。
- 新增薄型、有动作白名单和调用上限的单 Agent Controller，复用现有 `AIProvider`，不引入通用 Agent 框架或多 Agent。
- 新增来源中立的候选路线查询能力，复用现有会籍数据库和统一匹配图，分别返回满足条件、仅偏离一个条件和关键事实未知的路线；程序不替 Agent 做主观推荐。
- 复用现有持有会籍服务，在目录唯一识别且用户确认后持久化自然语言中提到的会籍。
- 新增受授权门控、只读、按候选调用的 StatusMatcher 经验调研，输出可比报告信号和来源链接，不写回正式事实或匹配图，失败时安全降级。
- 完整实现无方案分支：Agent 只提出一个最小调整；用户拒绝或调整后仍无方案时，Agent 主动询问是否持续跟进；确认后只保存一个等待目标。
- 扩展现有每日工作流，以确定性方式检查等待目标；无命中不调用模型，首次命中恢复同一个 Agent 并生成一次去重的应用内结果。
- 增加数据库迁移、配置、运行记录、自动化测试和真实自然语言端到端验收，确保前端只负责交互呈现、服务端负责所有业务规则。

## Capabilities

### New Capabilities

- `membership-strategy-agent`: 自然语言理解、确认门、候选路线联动、Agent 自主动作选择、个性化建议和前后端回合契约。
- `statusmatcher-experience-research`: 对最终候选执行受控的 StatusMatcher 实际申请经验调研并提供可追溯、可降级的观察结果。
- `membership-strategy-waiting`: 无方案最小调整、持续跟进确认、单等待目标持久化、每日确定性检查、首次命中恢复和去重呈现。

### Modified Capabilities

无。当前仓库尚无已同步到 `openspec/specs/` 的正式能力规格；现有会籍图、持有会籍和每日自动化行为保持兼容，本变更通过新能力组合复用它们。

## Impact

- 影响 `src/journeyplus/agent/`、`src/journeyplus/product/`、FastAPI 路由/静态页面、SQLAlchemy 模型、Alembic 迁移、配置和每日自动化入口。
- 复用 `AIProvider`、`StatusHoldingService`、`UnifiedMembershipTreeService`、现有事实读取与数据库会话，不新增第二套图或推荐事实库。
- 新增 Agent 回合状态与单个等待目标所需的最小持久化；不保存模型思维过程、完整长期聊天或 StatusMatcher 页面正文。
- StatusMatcher 网络访问默认关闭，只有服务端配置明确授权且已有最终候选时才可执行。
- 不引入 PydanticAI、LangGraph、LangChain、OR-Tools、向量数据库、Redis、消息队列、独立 Worker 或新的前端框架。
