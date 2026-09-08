# 当前工作区独立复核（2026-09-08）

## 结论

**当前实现尚未达到总纲要求的“系统侧全部调试完成、只待用户批准第三方模型验收”状态。** 上一轮 `system-review.md` 的完成判断过早；本报告取代其就绪结论，不删除原测试、人工运行或失败记录。

对六项规格、规范性设计附件、当前已跟踪与未跟踪实现、旧代码删除和现有验收证据重新核对后，增加了 11 个针对边界的本地复现；当前代码全部未满足其目标断言。发现 6 项 P1 和 5 项 P2 问题，并有 4 类架构及证据不足需要收口。这里的优先级用于本项目修复排序，不表示发生了生产事故。

原有全回归本轮仍为 626 passed / 5 skipped；另行重跑的 4 项隔离 PostgreSQL 测试通过。这些结果与新发现并不矛盾：原测试没有覆盖这些组合及故障边界，不能据其通过推导完整正确性。

本轮未调用任何第三方模型 API、未运行模型探针、未启动 Workflow。复现使用本地 FakeModel/无模型替身和 SQLite；PostgreSQL 仅使用显式隔离库。未修改产品实现，未创建 Git 提交，未部署、归档或 downgrade。

## 1. 完整性、正确性和架构一致性

| 维度 | 复核结果 |
|---|---|
| 完整性 | OpenSpec 清单 53/60 已勾；7 项含第三方模型门槛，依总纲延后是正确的。但已勾项中的系统侧完成声明需要重新验收，不能按 53/60 推算质量。 |
| 正确性 | 基本查询、展示、用户写入及模型接口已有实现和主流程证据；恢复、分页、覆盖、授权来源、跨轮展示、超时等仍有可复现缺陷。 |
| 架构一致性 | 通用 loop、独立配置、12 项注册工具、旧控制链退出、独立知识应用已成立；常规产品启动、服务端口与数据访问、阻塞执行边界尚未完全符合目标。 |
| 阶段结论 | 系统侧审查不通过；应先修复并复验，再提交用户审核。真实模型验收继续保持禁止。 |

| 规格 | 已有可靠基础 | 本轮否决或不足 |
|---|---|---|
| model-led-agent-harness | 核心不导入业务/SQLAlchemy；可替换 ModelPort；工具后可继续、直答合法；native/json 本地契约 | F01/F02/F03：启动失败隔离、同步阻塞、恢复投影；C01 端口未完整声明 |
| independent-agent-tools | 12 项能力、显式 query/patch、可选目录、只读知识与独立研究 | F05/F07/F08/F09：范围丢失、统计不实、limit 无效、来源截断丢失；C02/C03 数据边界与扫描 |
| agent-context-and-memory | 原始历史/笔记/产物保存；显式授权；会籍、journal、receipt 原子事务 | F03/F06/F07/F10/F11：恢复、导入授权来源、投影、回执重放、更新冲突 |
| model-owned-presentation | 纯构建器、模型顺序、同版简报链接、焦点与 SSE | F04：跨轮调用 ID 导致旧展示被复用；回放关联也需同轮作用域 |
| agent-workflow-isolation | Workflow 无 Agent import；知识应用可独立启动；Agent 不触发发布 | F01：常规产品入口仍共享模型启动故障；C02：实际读写 port 边界不完整 |
| agent-harness-migration-and-evaluation | 四表 additive、旧入口 410、旧对话只读/显式导入、失败保留 | F06 导入边界；C04 删除测试缺少行为逐项映射；11.6 的就绪判断不成立；模型门槛仍待批准 |

## 2. 必须修复的实现问题

### F01 / P1：常规产品启动仍被 Agent 模型初始化绑定

- 位置：`src/journeyplus/cli.py:292`、`src/journeyplus/product/api.py:40`、`src/journeyplus/product/agent_api.py:83`。
- `product-api` 无条件构造 AgentConfig/AgentModel；应用 lifespan 直接 await 模型初始化。配置缺少 context window 会在启动前失败；模型初始化抛错则整个产品应用不能启动，普通会籍、简报等页面也不可用。
- 本地复现：用初始化必定抛错的无网络模型替身创建产品应用，TestClient 启动失败，无法进入 `/holdings`。独立 `knowledge_server` 的存在没有解决常规产品入口的故障耦合。
- 对应：design D5/D8、独立业务所有权、非 Agent 页面保留、tasks 8.1/8.2/11.5。
- 修复要求：使产品业务应用能独立于 Agent 初始化启动；Agent 可用性由明确装配和局部状态管理，无模型模式不得构造客户端或探针。
- 证据：`test_product_pages_survive_unavailable_agent_model`。

### F02 / P1：同步数据库调用阻塞事件循环，超时、取消和并行保证不成立

- 位置：`src/journeyplus/agent/harness/registry.py:54`、`src/journeyplus/agent/tools/holdings.py:5`；routes/knowledge/waiting 等也直接执行同步 SQLAlchemy 服务。
- `async def` 包装并不会把同步服务变成异步。`asyncio.timeout` 需要事件循环获得执行机会；遇到慢 SQL、连接等待或锁等待，心跳和取消也会被延后。已有三读并行测试使用 `asyncio.sleep`，未验证真实同步业务读取。
- 本地故障注入：holdings.read 服务阻塞 60ms，工具 timeout=10ms，仍在约 73ms 后返回 EMPTY，而非超时结果。
- 对应：runtime 预算/取消、短事务及 lease、S05/R03、tasks 2.4/2.5/3.6。
- 修复要求：明确隔离阻塞工作，给数据库连接/语句/锁设置实际期限；处理取消后尚在执行的写入和回执。不能只加 `to_thread` 就声称写入已经取消。
- 证据：`test_sync_service_respects_tool_timeout`。这是本地慢服务注入，不冒称已经实测生产锁等待。

### F03 / P1：崩溃恢复绕过正常工具结果投影

- 位置：`src/journeyplus/agent/harness/runtime.py:241`、`src/journeyplus/agent/adapters/persistence.py:204`。
- tool_result 先保存完整原始结果；恢复发现缓存后直接返回完整 payload，绕开后面的 `bounded_result`。正常运行和恢复后的模型所见不一致，也失去正常投影附加的完整结果引用。
- 本地复现：在“完整工具结果已持久化、tool 消息尚未追加”窗口模拟中断。正常序列化结果约 9.4KB，恢复结果约 30.5KB；它绕过默认 12KB 单结果上限。更大的结果可能挤满当前轮并触发 CONTEXT_CAPACITY。
- 对应：recoverable context、durable resumable execution、T03/R03、tasks 3.5/3.6。
- 修复要求：新执行与恢复缓存使用同一投影路径、同一结果引用和预算规则；保留完整产物但不直接全量重新入模。
- 证据：`test_recovery_uses_same_bounded_projection`。上述数字是本地序列化大小，不是 provider token。

### F04 / P1：展示幂等键缺少 turn，后续轮次可能复用旧展示

- 位置：`src/journeyplus/agent/services/display.py:13`；`src/journeyplus/agent/adapters/persistence.py:306` 的展示索引及后续附件关联也只按 call_id。
- ToolCall 的数据库唯一约束是 `(turn_id, provider_call_id)`，展示却按 `(workspace_id, created_by_call_id)` 查旧值。模型适配器可替换，不能假设整个 24 小时会话所有调用 ID 都全局唯一；native 适配器没有跨轮规范化保证。
- 本地复现：同一工作区两个 turn 使用同一个 call_id，第一轮选择 First、第二轮选择 Second，第二次返回第一轮的 presentation_ref 和 First 内容。
- 对应：模型拥有展示选择、忠实回执/回放、P01/R01、tasks 7.2/8.2。
- 修复要求：产物幂等、块 ID、历史附件统一绑定 workspace/turn/call；同轮同键还应校验 payload 一致性，不静默复用不同选择。
- 证据：`test_presentation_call_id_is_scoped_to_turn`。

### F05 / P1：路线续页丢失未解析会籍与实际计算范围

- 位置：`src/journeyplus/agent/tools/routes.py:148`、`:191`。
- saved 搜索第一页明示 `unresolved_sources` 并置 PARTIAL；存入 ROUTES 的 snapshot 没有保存该解析范围，续页只读取原算法 coverage，可能变成 OK / complete=true。
- 本地复现：一个可解析会籍、一个 NEEDS_CONFIRMATION 会籍，两条候选分两页。第一页有 CATALOG_GAP，第二页缺失 unresolved_sources 且 complete=true。
- 对应：未解析会籍不得静默丢弃、progressive data、T01/T03、tasks 4.3/4.4/5.1。
- 修复要求：将 resolved/unresolved、实际输入和覆盖限制保存为查询结果快照的一部分；所有续页和 inspect 都继承同一范围，并区分“候选读完”和“全部起点已参与”。
- 证据：`test_saved_route_next_page_preserves_unresolved_scope`。

### F06 / P1：导入授权来源校验可被混合 message_refs 绕过

- 位置：`src/journeyplus/agent/services/user_memory.py:46`。
- 目前仅在引用消息“全部 legacy”时拒绝；quotes 又允许匹配其中任意消息。只要把一条新消息 ID 加进 refs，即使全部引用原话仍来自旧导入消息，也能通过。
- 本地复现：旧导入原话要求保存，新消息为“先不要保存任何东西”；refs 同时引用两条，但 quotes 仅引旧保存原话，工具返回 APPLIED。
- 这不是要求程序用关键词替模型判断授权语义，而是现有“导入原话不能授权”的来源校验不完整：新消息未提供任何被引用的新授权依据。
- 对应：charter §2/§3、导入不执行旧 pending、用户授权写入、A13/W、tasks 5.2/8.3。
- 修复要求：把每段 quote 与实际来源消息绑定；新授权必须有非 legacy 原话依据，导入材料只可作对象背景。语义判断仍由模型负责，不新增分类模型或“保存”正则。
- 证据：`test_imported_quote_needs_current_authorization_quote`。

### F07 / P2：通用裁剪后覆盖计数仍声称返回原始数量

- 位置：`src/journeyplus/agent/harness/context.py:83`、`:98`。
- 本地复现：原始 10 条结果裁成 3 条，`coverage.returned` 仍为 10；只将 complete 改 false 不能解释统计矛盾。候选与 route_refs 等关联列表还需要联合保真检查。
- 对应：charter §2、tools 共用覆盖契约、T03、tasks 3.5/11.4。
- 修复要求：区分源结果数量与当前投影可见数量，为被裁条目提供明确范围和恢复入口；不能保留含义已经变化的旧 returned/cursor 语义。
- 证据：`test_projection_counts_actual_visible_entries`。

### F08 / P2：workspace.read 的 refs/notes/presentations 分支不执行 limit

- 位置：`src/journeyplus/agent/services/workspace.py:14`、`:18`；`src/journeyplus/agent/services/artifact_views.py:16`。
- 本地复现：三个小 artifact、limit=1，一次返回全部三个且无 next_cursor。view 只有固定字节分页，没有接收 limit。
- 对应：tools T6 显式参数、progressive data、tasks 3.5。
- 修复要求：统一数量上限与字节上限；数量或字节达到上限都生成绑定原快照的游标，所有分支保持同一参数含义。
- 证据：`test_workspace_artifact_limit_is_honored`。

### F09 / P2：研究解析丢失原网页被截断的状态

- 位置：`src/journeyplus/agent/tools/research.py:58`、`:79`。
- PAGE 的 raw_truncated 没有传入解析、REPORT 或结果覆盖；解析成功后统一 complete=true。只保留 source_refs 并不能告知模型已解析的正文可能是不完整前缀。
- 本地复现：带合法报告头和正文、raw_truncated=true 的 PAGE 被解析为完整 1/1 结果；截断警告没有出现在返回数据。
- 对应：未知/未覆盖不得装作完整、原始研究证据、T03/N03、tasks 6.4。
- 修复要求：保留逐报告来源覆盖、截断/原文展开引用；截断影响结论时不得按完整正文判断结果，可明确 PARTIAL/UNKNOWN。
- 证据：`test_parse_truncated_page_preserves_incomplete_coverage`。首次探针的 HTML fixture 缺少必需节点，已修正为合法报告结构；首次失败保留，但不拿 fixture 错误作为缺陷证据。

### F10 / P2：等待操作重放重新制造 artifact，回执不稳定

- 位置：`src/journeyplus/agent/services/waiting.py:20`、`:86`。
- 含 pending_result 的 before 每次 project_goal 都新建 QUERY/ROUTES 产物。同一个 operation_key/payload 重放返回不同的 result_snapshot_ref/route_refs；重放分支还在用户写事务中通过另一个连接创建产物，和首次路径的事务外投影不一致。
- 本地复现：等待命中后 update，同参数再调用，operation_ref 相同但 before.result_snapshot_ref 改变。业务写没有重复提交，但“返回原回执”和引用稳定性没有实现。
- 对应：atomic idempotent writes、W01/W02、tasks 5.4/5.5。
- 修复要求：为同一工作区和持久回执建立幂等投影；跨工作区确需重新引用时显式区分持久回执和临时视图。投影移到用户事务外，避免每次重试追加相同大结果。
- 证据：`test_waiting_replay_preserves_receipt_refs`。

### F11 / P2：会籍更新到已存在项目时返回可重试工具故障

- 位置：`src/journeyplus/agent/services/user_memory.py:94`、`:101`，`src/journeyplus/agent/harness/registry.py:69`。
- create 检查 program_key 冲突，update 修改身份却直接 flush。数据库唯一约束阻止重复，但异常被转换为 TOOL_ERROR/retryable=true，没有返回冲突记录与 revision。
- 本地复现：已有两个项目，将第二张会籍更新成第一张的项目，实际返回 TOOL_ERROR，而非业务 CONFLICT。没有证据表明重复会籍已经写入；问题是错误类型和可恢复信息错误。
- 对应：工具结构化错误、会籍自然键冲突、W03/A08、tasks 5.3。
- 修复要求：事务内校验目标自然键，捕获并发唯一冲突并返回当前对象/ref/revision，不能建议盲目重试。
- 证据：`test_update_to_existing_program_reports_conflict`。

## 3. 架构及证据还需收口的部分

### C01：端口声明未覆盖实际依赖，服务仍穿透具体存储

`harness/contracts.py:152` 的 SessionStore Protocol 没有声明 runtime 实际调用的 request_cancel/heartbeat/tool_intent/tool_result；ExecutionContext 的 artifact/authorization 为 Any。workspace/display 服务经 `authorization_port.factory` 直接取 SQLAlchemy 事务。核心 import 边界成立，但“可替换端口”尚未被完整契约约束。

应补齐实际最小接口，将笔记、展示和授权查询的存储操作封装到清晰端口，增加独立替身装配测试。无需为每个函数加转发层，但不应把能访问全部具体存储的对象称作受限授权端口。

### C02：知识读源与用户读源没有完全按方案分开

`composition.py` 接收 read_factory，但正式 server/CLI 未落实 migration.md 的独立读库配置。routes.evaluate 从 knowledge.read Session 读取 StatusHolding；UserMemory 和 WaitingService 又用可写 factory 查目录/正式路线。默认同库时能工作，不能据此证明受限知识凭据或独立读源可替换。

应让用户会籍快照经用户数据服务进入路线计算，目录和发布对象经知识 port 读取，并验证受限权限下的装配。当前未发现这些路径主动写正式知识；这里是权限和依赖边界未闭合，不能误报为已经污染正式库。

### C03：输出有界不等于数据库读取和计算有界

`services/snapshots.py:24` 为目录/活动/路线每次调用扫描 Activity、全部 ActivityKnowledgeVersion、Program/Tier/Alias；IdentityService 每次绑定又读取全目录；history/artifact 搜索在内存过滤全记录。常规分页调用也会先做重复快照扫描。

这部分不会把数据库全部内容直接传给模型，但会增加服务内存、SQL 时间和事件循环阻塞。应以发布/目录 revision、必要列和 SQL 查询构建快照/检索，在代表性数据量下测量。不能把现有小库的通过结果当作此项效率已达标。

### C04：旧测试退役与新证据之间缺少逐行为映射

当前删除 30 个旧测试文件，含 197 个测试函数。强制 PLAN、关键词门、固定确认等确应退出，删除本身不等于错误；但其中也包含网络大小边界、部分读取失败、等待结果去重等继续有效的行为。现有证据主要按文件和场景类别汇总，尚不足以确认每项保留语义均被新断言替代。

应补“旧行为 → 明确废弃依据 / 新测试与人工证据”的映射。不能要求恢复旧固定流程测试，也不能用没有旧 import 证明能力覆盖完整。原人工证据可继续证明其具体轨迹，但没有覆盖本轮发现的组合边界。

## 4. 本轮验证与证据

私有证据根：`.secrets/agent-harness/20260908/`。均不含新的第三方模型调用。

| 材料 | 结果及界限 |
|---|---|
| independent-audit-existing-regression.txt | 原 tests/ 全量：626 passed、5 skipped，exit 0；本轮新增红测位于私有目录，不混入该数量 |
| independent-audit-postgres.txt | 4 passed；显式 `journeyplus_eval_pg_20260908final`，2.70 秒；不等于本轮 11 项问题全部做过 PG 复现 |
| test_independent_audit.py / independent-audit-regressions-r2.txt | 11 项目标契约断言全部失败；本地模型替身、SQLite 和慢服务故障注入 |
| independent-audit-first-attempt.txt | 首轮 8 个探针；保留研究页面 fixture 缺失节点导致的无效初次复现 |
| independent-audit-worktree.json | 与上一轮 source_hashes 对比无差异；登记旧文件及 197 个被删测试函数，证明问题存在于上一轮交付代码而非此次产品修改 |
| independent-audit-database.json / .txt | 隔离 review/template 的 44 张正式及来源表哈希一致；9 个人工工作区的 artifact 哈希与工具结果作用域一致，原测试会籍已删除、3 条 journal 保留。不能把这些结果等同于所有回执、投影及上下文语义正确 |
| OpenSpec strict / git diff --check | 本轮通过；只证明文档结构和补丁格式，不证明功能正确 |

全量回归中第 5 个 skip 是 PostgreSQL 发布触发器测试；其上轮单独通过证据仍保留，本轮未将其算入 4 项 harness PG 重跑。上一轮默认本机库意外升级的历史披露继续有效，本轮隔离核对不能改写该历史。

本轮没有重新运行全部人工 ModelPort 对话或浏览器场景，没有用这些局部模拟复现冒充新的完整人工验收。修复后仍需按总纲逐步人工复验受影响链路，包括真实数据库、展示和恢复结果。

## 5. 下一阶段顺序和完成声明

1. 先修 F01–F06 及相关端口/阻塞边界；补对应持久化、取消恢复和跨轮一致性测试。
2. 修 F07–F11，统一有界结果、覆盖和引用契约，再检查 12 个工具的成功/失败/分页分支。
3. 收口 C01–C04；复验真实隔离数据库、人工模型位置输入输出和浏览器回放，保留此次红测及修复轨迹。
4. 更新任务、证据矩阵和系统审核包。只有所有系统阻塞项解决，才重新向用户申请最终模型验收审核。

已勾选的 2.4/2.5/3.5/3.6/4.4/5.2/5.3/5.4/5.5/6.4/7.2/8.1/8.2/8.3，以及 11.2–11.6 的系统侧结论，应按本报告重新核对；保留原勾选记录不表示仍认可其全部完成。本次只做审计，未把修复标为完成。

目前准确的阶段描述是：**目标架构的主体和主要能力已实现，主流程有真实证据；系统正确性与边界收口尚未完成，不能进入第三方模型验收。**
