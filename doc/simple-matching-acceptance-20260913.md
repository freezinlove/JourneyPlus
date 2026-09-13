# 统一会籍匹配精简验收（2026-09-13）

## 结论与范围

Agent 路径查询、后台等待、`/explore`、个人匹配树和统一会籍树共用确定性最短路径选择。核心关系为会籍项目／等级映射，费用只作为免费／付费开关；地区、金额、币种保留在活动详情，不参与路径分支或优化。不改数据库模型、AIWorkflow、模型端口或 Harness 调度，不增加模型生产调用。

多起点 BFS 为每个节点保留一个最短前驱；过滤付费连接后再找免费路径。默认每个目标项目选最高可达等级，明确指定等级时尊重指定值。剔除闭环、已持有起点、重复目标尾段及已被较长结果包含的独立前缀。最终图共享节点／连接各画一次。搜索过程不存档；仅最终路线按需分页进入现有临时工作区产物。

旧查询含金额、地区等条件时要求重新计算；旧等待结果保持历史只读，旧活动事实没有被清除。旧任务的条件不会被悄悄改写。新等待任务版本为 4，首次找到结果后暂停；不监控价格波动。等待结果签名忽略仅金额／地区或版本变化，保留活动身份、会籍连接和付费状态的区别。

## 真实生产验收

从正常浏览器 `/workspace` 输入自然语言，使用正式 PostgreSQL、正常 Agent 服务和真实 `qwen3.8-flash`。保留原有显式缓存配置，没有替换工具执行、预写模型调用序列或使用隔离库代替生产验收。自动化边界测试另行运行，不混同真实验收。

工作区：`297396e7-10ef-4538-b2ef-8ad58ca4db34`。共 9 轮，全部 COMPLETED。18 次工具尝试中 17 次成功；最后一轮模型给 `waiting.manage list` 多传 `goal_ref`，收到参数错误后自行去掉并重试成功。没有路由存档超限、执行异常或失败回合。

| 场景 | 核对结果 |
| --- | --- |
| 假设 BA Silver，允许付费，全部匹配 | 5 条最终路线，6 个目标节点；Flying Blue Gold 作为通向 Royal Jordanian 的中间节点，不再单列重复前缀 |
| 同起点，只看免费 | Asante Rewards Gold Elite Plus、Club Avolta Gold 两条；与页面一致 |
| 同时假设 BA Bronze + Silver，目标 Flying Blue | 仅选 BA Silver → Flying Blue Gold，隐藏独立的较低 Silver 目标 |
| 明确只要 Flying Blue Silver | BA Bronze → Flying Blue Silver；不替换为 Gold |
| 明确询问 Silver 地区价格 | 模型读取既有活动详情，返回希腊 EUR 89、其他已记录地区 USD 99；金额未进入搜索条件 |
| 等待 BA Silver → Flying Blue Gold | 正常后台维护命中 RESULT_PENDING；模型读取并画出的路径、版本与直接查询一致 |
| 取消等待及无结果查询 | 本次等待已 CANCELLED；Club Avolta Gold → Flying Blue Gold 返回当前库内无路径，未保存假设会籍 |
| 等待能力说明复验 | 正确解释“命中即暂停”，确认所有历史等待均已取消 |
| `/explore` 正常页面 | 允许付费／仅免费分别与 Agent 的 5／2 条路线一致；一张图，无金额输入控件 |
| 图中点击 Flying Blue | 同版详情仍有 104 项映射和四组地区价格、申请入口；刷新后图恢复正常 |

BA Silver 全部结果仅展开 7 个节点、检查 17 条连接。共享查询结果 8,768 字节；真实 Agent 最终 ROUTES 存档最大 11,813 字节，远低于原来触发故障的 1 MB 限制。逐项核对六条输出连接的 `mapping_ref` 与正式 FactSet 映射：Air Astana、Asante、Club Avolta 通配规则、Lotusmiles、Flying Blue、Royal Jordanian 均相符。该核对使用结构化映射，不要求逐字段原文证据。

重启加载最终工具说明期间有一次 HTTP 503（服务尚未就绪），状态恢复 READY 后正常重试完成；没有创建失败回合或重复写入。

## 自动化边界验收

67 项 Python 测试、9 项前端测试通过。覆盖：环路、较长重复尾段、共享前缀、多个起点、已持有节点、较长免费替代路径、最高等级、必要低等级中转、指定较低等级、未知等级顺序、空结果、状态上限、45 节点／1,980 条边的密集图、最终结果分页无丢漏、跨快照引用、旧条件失效、旧等待只读、等待与直接查询一致、金额变化不重复触发、活动生命周期及历史日期、原始模型读取、详情版本绑定、图节点／边去重。

执行文件：`test_simple_matching.py`、`test_agent_workflow_reads.py`、`test_unified_membership_tree.py`、`test_product.py`、`test_agent_lifecycle.py`、`test_product_brief_versions.py`、`test_agent_route_recall.py`、`test_route_details.py`、`test_harness_waiting.py`；前端为 `route_graph.test.mjs`、`route_step.test.mjs`。另通过 OpenSpec 严格校验、Python 编译及 `git diff --check`。这是改动相关回归，未声称全仓所有历史测试都已运行。

## 正式数据保护

实施前后逐行比对一致：`status_events` 7 行、`fact_sets` 13 行、`briefs` 13 行、`article_analyses` 1 行、`article_opportunities` 1 行、`article_briefs` 1 行。`status_holdings` 始终 0 行。没有数据库迁移、清表或修改生产事实。

原来的 6 个等待任务逐行未变。验收新增任务 `bf0de3f2-f14e-4d90-8b5b-7d81f578b0dc` 已通过正常模型工具取消，保留正常操作记录；新增对话及图产物按既有工作区生命周期处理。

原始验收 JSON、数据库比对、日志及测试输出均保存在已忽略的 `.local/agent-audits/simple-matching-20260913/`，不放进 doc，也不加入 Git。本报告和 OpenSpec 为可追踪的说明。

## 边界与限制

- 等级排序使用明确项目梯度。当前正式库参与此次搜索的目标顺序均已知；未来未知项目无法可靠比较等级时保留候选并标明未知顺序，不凭名称猜测最高等级。
- 同一目标存在多种地区价格时不区分路径；有必付费用则按付费。可选附加费不算必付，缺少费用信息按免费。这是产品计算口径，详细申请限制仍在活动资料中。
- “完整”指当前已记录、可计算关系的简化覆盖，不保证覆盖现实全部机会。技术资源不足时明确标示未完成，不伪装成无结果。
- 真实模型早期把等待说成持续监控，后续补清工具说明并复验纠正；仍不能据单次测试保证模型自然语言永不误述。核心路径、费用开关与等待状态由程序决定。
