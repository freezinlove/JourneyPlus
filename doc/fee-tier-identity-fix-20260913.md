# 费用等级名称对齐修复与验收（2026-09-13）

## 修复结果

已修复 Asante Rewards、Royal Jordanian 的正式价格等级带项目名前缀、图等级省略前缀而导致的免费误判。正式 Agent 服务已重启，等待功能仍关闭。

在当次正式库中，假设仅持有 BA Silver：

- 仅免费：只返回 Club Avolta Gold。
- 允许付费：仍返回 5 条最终路线；Asante 为付费，BA Silver → Flying Blue Gold → Royal Jordanian Gold Sparrow 的两步均为付费。
- Club Avolta 仍为免费，Flying Blue 原有收费判断不变。

## 实现范围

将已有图的项目名前缀处理提取到 `membership/normalization.py`，由官方图、统一会籍图和费用读取共用。费用匹配对价格等级、查询目标等级双方采用相同的项目上下文和等级规范化；只剥离已知目标项目的名称或别名，不用通用后缀猜测、不为活动增加特例。

`WorkflowRouteService` 使用图中已有的目标项目别名；个人图费用标签复用已有目标项目别名规则；详情费用标签的二次比较也使用相同规范化，避免已选价格再次被丢弃。原有共同前缀别名发现规则只是移到公共位置，没有新增发现规则。

没有修改数据库模型、生产事实或 AIWorkflow，也没有修改地区分支、最低跳数、最高目标等级等搜索规则。必付费、可选费、零费用和缺少费用的现有口径保持不变。没有增加固定模型调用步骤。

已有对话中的旧图是历史快照，保留当时的结果；重新查询生成正确的新结果，不改写历史产物。

## 正式服务真实对话

通过正常浏览器 `/workspace` 输入自然语言，正式 PostgreSQL、正式服务及真实 `qwen3.8-flash`；显式缓存配置保持开启。没有用测试模型、隔离库或预写工具调用代替。

工作区：`7282ccf5-71e6-4ef0-9476-c6804e8727b8`。

| 轮次 | 用户请求 | 模型实际调用 | 验收 |
| --- | --- | --- | --- |
| 1 | 假设 BA Silver，所有免费路径，一张图，不保存会籍或等待 | routes.evaluate search → display.present；3 次模型请求 | 只有 BA Silver → Club Avolta Gold，免费；图和回答正确 |
| 2 | 允许付费，其余条件不变；解释 Asante、Royal Jordanian 每一步是否付费 | routes.evaluate search → 两次 activity.read → display.present；4 次模型请求 | 保留起点，只解除 free_only；5 条路线，Asante 付费，Royal Jordanian 两步均付费 |

两轮均 COMPLETED，6 次工具调用均成功。逐项核对模型参数与执行参数一致、初始工具观察没有 omissions、6 个展示路线对象与各自快照一致；全部最终连接的费用标记正确，活动版本存在。两次详情读取的 15 条价格，与对应正式事实的金额、币种、等级和可用性一致。没有 holdings.write 或 waiting.manage 调用。

另独立按正式事实中的明确等级名称检查 Asante、Royal Jordanian、Flying Blue 的正金额申请费，以及 Club Avolta 的明确免费说明；不是仅比较两个共享计算器的输出。个人匹配图的六个费用标签也核对正确。

本次没有保存模型 HTTP 请求体，因而不声称逐字复核每次供应商输入或确认实际缓存命中。审计对象包括持久化调用、工具观察、事实及页面回复。

## 回归与数据保护

70 项相关测试通过：费用身份新增 14 项，以及简单匹配、产品、统一会籍图、官方图、路径详情、Agent 读取和等待开关回归。覆盖完整前缀与简短等级双向匹配、大小写空格、已知别名、最长前缀、不同项目、不同等级、Gold 与 Gold Plus 区分、可选费、不可申请价格、零金额、通用费用、无费用，以及免费搜索和个人图的集成路径。

额外执行 `test_architecture_read_fixes.py` 时有两条旧断言失败，已在提交前代码中同样复现：旧测试期望“收费但金额未公布”仍出现在免费候选中，以及“费用待公布”返回旧的非免费证明候选语义。当前二元费用实现并非这种返回方式。本次没有改动这些原有行为或删改断言，不能宣称该测试文件全绿。

实施前后逐行比较相同：status_events 7、fact_sets 13、briefs 13、article_analyses 1、article_opportunities 1、article_briefs 1、status_holdings 0、agent_wait_goals 7。未改数据模型或清理业务数据。

原始快照、独立事实核对、两轮调用记录和检查结果保存在 Git 忽略目录 `.local/agent-audits/fee-tier-fix-20260913/`，未把原始 JSON 放进文档目录。修改保留工作区，未提交。
