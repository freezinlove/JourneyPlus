# 对照目标架构的全仓库审计

审计日期：2026-09-09（Asia/Shanghai）。基线分支 `codex/clean-system-architecture`，HEAD `8ba16bc`；新 change 文档仍在工作区，业务代码未修改。本报告只记录本轮重新取得的证据，不继承旧 change 的问题编号、勾选或验收结果。

**结论：两个板块的主要边界已有实现，值得保留；整个项目仍处于新旧结构并存的过渡状态，尚未达到新目标。当前正常库已接入，知识页面和一条真实网页图查询可用；不能据此宣称 Agent 对话、重新生产和故障恢复已完成系统验收。**

## 1. 审计范围与证据强度

覆盖清点：604 个已跟踪文件、207 个产品 Python 模块、17 个脚本、28 个版本迁移及 2 个迁移支撑文件、16 个产品静态文件；56 个 ORM 表及正常数据库全部 57 张表（含 Alembic）。全量文件/依赖索引与关键调用链阅读相结合，不宣称每行代码都经语义证明。

- **运行证据**：当前端口进程、正常 HTTP 只读接口、实际浏览器页面、数据库只读事务及外键核对。
- **代码证据**：实际入口、依赖、调用顺序、事务、查询、上下文和展示实现；重要缺口给出定位。
- **辅助检查**：现有本地测试及小型离线反例，不替代网页系统验收。本轮未向 Agent 或 Workflow 提供方发起模型请求，也未联网重新采集来源。
- **待验收**：事实是否完整忠于重新取得的原文、真实模型对话表现、长历史语义保持、完整故障恢复，留在后续正常网页验收阶段。

证据索引：

| 文件 | 内容 |
|---|---|
| [runtime-baseline.json](evidence/runtime-baseline.json) | 采样时间、分支/提交、脱敏磁盘配置、数据库身份、全部库名称/大小、来源数量与当前活动 |
| [runtime-http.json](evidence/runtime-http.json) | 当前 API 状态、35 个 OpenAPI 路径、进程信息、文件修改时间、相关暂停自动化配置 |
| [source-map.json](evidence/source-map.json) | 207 模块的哈希、定义、导入位置，56 ORM 表的声明及直接导入消费者 |
| [database-schema.json](evidence/database-schema.json) | 全部 57 张表的行数、字段类型、主键/外键/检查/唯一约束及索引 |
| [repository-inventory.json](evidence/repository-inventory.json) | 仓库顶层、脚本、迁移、静态文件和项目临时目录清点 |
| [integrity-checks.json](evidence/integrity-checks.json) | 84 项外键孤儿检查、等价目录分组、提示词指纹、网页自动创建的空会话 |
| [targeted-checks.json](evidence/targeted-checks.json) | 离线交付反例、工具定义估算、现有运行状态汇总及发布/简报一致性计数 |
| [local-checks.txt](evidence/local-checks.txt)、[local-checks.xml](evidence/local-checks.xml) | 本轮 115 项辅助测试原始结果：114 通过、1 失败 |

直接导入索引不是精确 SQL 读写跟踪：动态导入、通用 Session 操作和原始 SQL 须结合本报告的调用链判断。没有消费者索引不能单独作为删除依据。证据中的数据库对象名不是删除授权清单。

## 2. 当前真正运行的系统

### 服务与数据库

- `127.0.0.1:8023`：PID **66382**，2026-09-09 **15:28:44** 启动；工作目录为本仓库，命令为 `.venv/bin/journeyplus product-api --host 127.0.0.1 --port 8023`。
- Docker 容器 `journeyplus-postgres-1`，PostgreSQL 17.11，宿主端口 **5433**。正常库 **journeyplus**；本轮 SQL 会话强制 `default_transaction_read_only=on`，元数据/计数清点使用可重复读快照。
- 磁盘配置：知识读取 `unified`、知识发布开启、用户写入未暂停；Workflow 为 `deepseek-v4-flash`，Agent 为 `qwen3.8-flash`、native、上下文窗口 32768。90000/120000 是**整轮累计输入预算**，不是单次请求的窗口大小，不能据此推断单次输入 12 万 token。
- 当前 `/v3/agent/status` 返回 `READY`、知识 `AVAILABLE`，目录 128 项目/433 等级、8 个已发布版本；`/v2/rollout` 返回 unified。正常 API 万豪目录 ID 与正常库一致。
- 已确认的写入者：正常 API 的会籍/等待/会话写入；Agent 生命周期恢复与每 60 秒维护；Workflow CLI 的采集/处理/发布、review API、人工维护脚本。当前只有一个本仓库 Python 服务进程；匹配到的 Codex 每日采集自动化为 **PAUSED**。未发现用户 LaunchAgents 中 JourneyPlus 引用；这些是采样结果，停写前仍须重新核对。

### 数据实况

| 数据 | 当前数量与含义 |
|---|---|
| 来源项 / 文档版本 | 160 / 214，包含多个历史来源 |
| 旧活动 / 事实版本 / 简报 | `status_events` 8、`fact_sets` 66、`briefs` 68 |
| 旧文章分析 / 文章活动 / 简报 | 62 / 23 / 23 |
| 正式活动 / 版本 / 简报 | 8 / 8 / 8；本次采样简报均 READY，无“已发布但无 READY 简报”现存行 |
| 正式方案 / 映射 / 价格 | 16 / 591 / 35；价格映射关联 6 条，数量本身不证明费用缺失或错误 |
| 迁移关联 | `knowledge_migration_links` 1147 条，当前生产仍引用该能力 |
| 用户数据 | 2 条会籍、1 条等待目标；处置范围尚未明确，不能作为旧知识顺带清空 |
| Agent 历史运行 | 14 轮，其中 9 PARTIAL、5 COMPLETED；属于既有记录，不是本轮测试结果，也不能据此计算本轮成功率 |
| 数据库结构完整性 | 84 项已声明外键检查未发现孤儿；当前活动指针未发现跨活动/缺失版本。仅证明引用完整性，不证明事实语义正确 |

LoyaltyLobby 有 96 来源项、97 文档，发布时间范围 2026-08-04 至 2026-09-04（UTC）。当前正式活动全部由 `legacy:status_events:*` 身份关联，含已关闭的 GHA。未看到正式文章活动并不等于系统从未采集文章；需要同时看旧文章产物和现存准入条件。

### 正常网页观察（范围有限）

实际打开 `/workspace`，从导航进入 `/knowledge`，加载 8 个活动卡片；进入 `/explore`，查询 Marriott，选择 **PLATINUM ELITE**，执行图查询：页面返回已找到 23 条，首屏 12 条，并明确资料/搜索覆盖限制及费用未知。界面提供继续展开及版本简报入口。本轮没有把这一个样本扩展为全场景通过，也没有审核这些来源事实是否仍符合今天官网。

网页 `workspace_v3.js:145` 在新浏览器会话初始化时自动 POST 创建空工作区，因此本轮导航产生了 **1 条空会话**（`1d1adea8-e57e-4481-bbbc-41b335a3257e`，消息数 0）；没有发送消息、启动模型轮次或修改会籍/等待记录。该空会话已列入证据，未在审计阶段擅自清理。

## 3. 当前链路与目标对比

### AIWorkflow 生产链

```text
邮件/订阅/公开页面
  → sources + content（来源项、原始/规范文档）
  → StatusMatch watch/三页采集 或 普通文章筛选与理解
  → status_events/fact_sets/briefs 或 article_analyses/opportunities/briefs
  → run-daily 的可选 knowledge_outputs，或显式 knowledge-refresh
  → KnowledgeRefreshService：旧业务身份/目录 → 绑定实际文档
  → KnowledgeWorkflow：准备 → 提取与校验 → PublicationService
  → activities/versions/options/mappings/prices/evidence
  → 发布之后补生成 activity_briefs
  → 知识页面与共享 RouteService
```

证据：[automation/service.py](../../../../src/journeyplus/automation/service.py:467)、[refresh.py](../../../../src/journeyplus/knowledge/refresh.py:77)、[workflow.py](../../../../src/journeyplus/knowledge/workflow.py:205)。

**保留的必要能力**：采集去重、原文及章节、官方三页绑定、文章分类/一文多活动拆分、目录身份、确定性表格解析、证据/价格/条件校验、活动期次处理、增量发布。尤其 [table_groups.py](../../../../src/journeyplus/knowledge/table_groups.py:27) 直接使用 FAQ 结构与规范章节生成有证据的映射，不应当因它复用 `facts/statusmatch_tables.py` 就删掉。

**需改的部分**：上述必要能力最终输出同一知识草稿/发布契约；不再先生成一套可独立消费的旧事实和旧简报，再转到新身份并重新提取。不是删除 AIWorkflow，而是收敛它内部的重复权威结构和发布入口。

### Agent 消费链

```text
workspace_v3.html/js
  → /v3/agent/workspaces/.../runs + SSE
  → AgentLifecycle → Runtime（ModelPort ↔ 独立工具）
  → KnowledgePort → ActivityReadService / RouteService
  → 用户数据服务（仅授权会籍/等待操作）
  → 原始调用/结果/快照/回执 → 上下文投影 → 模型下一步
  → BusinessCompletion + 展示服务 → SSE/页面
```

[composition.py](../../../../src/journeyplus/agent/composition.py:25) 装配 12 个工具；[runtime.py](../../../../src/journeyplus/agent/harness/runtime.py:112) 是通用循环；[access.py](../../../../src/journeyplus/knowledge/access.py:22) 提供只读知识事务；[knowledge_public_api.py](../../../../src/journeyplus/product/knowledge_public_api.py:53) 与 Agent 的 [route_query.py](../../../../src/journeyplus/agent/services/route_query.py:83) 使用同一个 `RouteService`。

**已对齐**：本轮 AST 和边界测试未发现 harness 导入业务 ORM/Workflow、工具或服务重入 Agent 控制器、Workflow 依赖 Agent 执行。`agent/server.py`、`knowledge_server.py` 有独立入口；Agent 模型失败被生命周期限制在 Agent 就绪状态。业务查询和工具之间存在共享服务是合理复用，不等于工具互相耦合。

**尚未对齐**：正常装配仍挂接旧路由/历史导入；人工 ModelPort 未接网页；受控的逐请求模型输入审计不足；完成检查仍有明确能力边界。上下文已有渐进披露，但长历史语义和真实模型效果尚不能判定通过。

## 4. 已确认差距及整改依据

这里按根因归并，不为了凑问题数量拆分。同一项可能跨多个模块。

### A1 · 当前运行版本与工作区不一致（验收前必须处理）

- **事实**：服务启动后 `instructions.md`、`harness/context.py` 于 15:33:30 修改。当前服务新建工作区写入 `harness-327a11eec7e914c3`，工作区现有指令按相同 digest 算法应为 `harness-dae364eaa96a101e`，不是只凭 mtime 推测提示词不同。
- **影响**：对磁盘代码的检查不能证明用户正在用的行为；现有状态接口不返回部署代码/指令配置指纹。
- **依据**：目标 §6、§8；[composition.py:13](../../../../src/journeyplus/agent/composition.py:13)、[persistence.py:44](../../../../src/journeyplus/agent/adapters/persistence.py:44)、runtime/integrity 证据。
- **整改**：统一启动与部署基线，显式记录进程加载的代码/指令/工具/库版本；重启后核对再验收，不依赖“文件已修改”。本轮不重启。

### A2 · 生产仍依赖旧业务事实和迁移身份（结构性改造）

- **事实**：`official()` 必须已有 `StatusEvent`，读取 `FactSetRecord` 初始化目录；`article()` 必须已有 `ArticleOpportunityRecord`。`_identity()` 创建 `legacy:*` 并调用迁移 `_link`。StatusMatch 阶段已生成旧事实和模型简报，普通文章亦如此，之后新知识链再次从文档提取。
- **影响**：不能直接删旧事实表；空库只建立目标知识表后，现有日常生产入口无法闭环。多套权威消费结构和重复提取/简报开销继续存在。
- **反证/限制**：`_identity` 没把旧映射直接当新正式映射；新事实从绑定原文提取。不是所有阶段都重复，也不是 AIWorkflow 应被移除。
- **依据**：目标 §2、§3、§5；[refresh.py:41](../../../../src/journeyplus/knowledge/refresh.py:41)、[project_workflow.py:1233](../../../../src/journeyplus/statusmatch/project_workflow.py:1233)、[article_operations.py:302](../../../../src/journeyplus/article_operations.py:302)。
- **整改**：让来源身份、文章拆分、目录和确定性解析直接准备正式 `KnowledgeDraft`；处理中间结果保留草稿用途。替换身份关联后再退出旧事实/旧简报/迁移链接及旧消费者，不靠长期双写。

### A3 · 正式发布与简报准备顺序不符合原子就绪目标

- **事实**：`PublicationService.publish` 先 PUBLISHED 并切 `current_version_id`，插入待生成简报；`KnowledgeRefreshService._process` 在提交后再 `_briefs()`。简报失败只标记 FAILED，当前版本不恢复。
- **影响**：存在正式版本对外可读但必要简报未就绪的窗口，生产结果可能是新知识已发布/简报失败。现存 8 条都 READY，**不是说当前已出现破损简报**。
- **依据**：目标 §2“统一发布”；[publication.py:458](../../../../src/journeyplus/knowledge/publication.py:458)、[refresh.py:213](../../../../src/journeyplus/knowledge/refresh.py:213)、[briefs.py:8](../../../../src/journeyplus/knowledge/briefs.py:8)。
- **整改**：将确定性简报和图可计算性校验纳入待发布准备，最后短事务一起切换。复用版本读取/投影，不需要引入队列或第二库。

### A4 · 一次性清理被固化成来源准入；初始化入口仍停在旧产物

- **事实**：`ingestion_scope.py` 固定以北京时间 2026-09-06 为 LoyaltyLobby 长期准入下限；正常 refresh 和 backfill 调用它。现存 LoyaltyLobby 全部早于该下限。`initialize-window` 只接受 2026-07-15 至 08-22 的固定批次；`initialize-mail-details`/该窗口流程没有统一知识 refresh 调用。
- **影响**：与一次性清理要求不同；照旧初始化命令不能证明今天新资料已进入 Agent 消费结构。
- **依据**：目标 §7；[ingestion_scope.py:5](../../../../src/journeyplus/knowledge/ingestion_scope.py:5)、[refresh.py:156](../../../../src/journeyplus/knowledge/refresh.py:156)、[initialization.py:57](../../../../src/journeyplus/automation/initialization.py:57)。
- **整改**：本次来源范围做成明确的执行清单；正常生产不保留清理日期限制。新初始化入口从真实来源一直执行到目标发布产物，输出每阶段状态。GHA 对象的一次性排除记入清单，不能生成永久禁采规则。

### A5 · 正常产品仍装配旧消费入口和历史兼容

- **事实**：`create_product_app` 仍导入旧 `UnifiedMembershipTreeService`/`ProductBriefService`/`PersonalizedMatchService`，注册 `/v1` 目录、会籍及业务读接口；rollout 决定屏蔽/重定向。Agent API 仍挂旧 workspace 读取和导入，新页面含导入逻辑；知识 API 提供 legacy opportunity 映射。
- **影响**：最终项目不是唯一目标结构；删除旧表会同时影响 CLI/review API/历史入口，而不是只删一个开关即可。
- **依据**：目标 §3、§6；[product/api.py:14](../../../../src/journeyplus/product/api.py:14)、[rollout.py:5](../../../../src/journeyplus/product/rollout.py:5)、[knowledge_api.py:35](../../../../src/journeyplus/product/knowledge_api.py:35)、[persistence.py:430](../../../../src/journeyplus/agent/adapters/persistence.py:430)。
- **整改**：先迁出仍必要的会籍管理、审核和知识查看功能；退出旧读取/导入/迁移开关，再删旧消费者。会籍实体及规范化算法不能随旧页面一起误删。是否保留 `/v1` 路径名不是关键，不能继续读取旧业务结构。

### A6 · 人工 ModelPort 与逐请求观察未接正常网页

- **事实**：`scripts/review_agent_harness.py:77` 拒绝正常库，只允许 `journeyplus_eval_*`；直接 `store.create/start`、`runtime.run`，没有网页/API/SSE。正常服务调用模型时未持久化该次完整 projected input、wire 工具定义和对应 per-request usage；模型 `metrics` 为内存列表，运行 checkpoint 保存累计预算。
- **影响**：已有人工脚本无法按新方法完成双视角验收；现有完整消息记录不等于每次模型实际看见的投影，事后精确重建存在缺口。
- **依据**：目标 §4、§8；[review_agent_harness.py:77](../../../../scripts/review_agent_harness.py:77)、[runtime.py:145](../../../../src/journeyplus/agent/harness/runtime.py:145)、[model.py:335](../../../../src/journeyplus/agent/adapters/model.py:335)。
- **整改**：保留同一服务/库/API，只替换可注入 ModelPort；为验收提供有范围的输入/输出观察记录，关联 run/attempt/call，不额外建设一套产品。旧脚本可保留诊断价值或合并退出，但不能继续作为系统验收入口。

### A7 · 完成交付检查只能验证声明，不能作为成功保证

- **事实**：`Answer.deliveries` 默认空；只遍历模型提供的声明。离线反例中只有一个目录调用，没有写入或展示回执，最终文本声称“已保存会籍，所有匹配路线都已展示”，`deliveries=[]` 仍被接受。精确引用若指向对象/数组，当前 renderer 直接 `json.dumps`，存在原始结构进入正文的路径。
- **影响**：检查通过并不证明用户请求被执行或事实陈述有依据，不能用 COMPLETED/合法 JSON 承诺正确性。此反例是确定性契约检查，不是本轮真实模型产生的错误。
- **依据**：目标 §4“展示与交付检查”；[completion.py:25](../../../../src/journeyplus/agent/services/completion.py:25)、[completion.py:93](../../../../src/journeyplus/agent/services/completion.py:93)、[completion.py:147](../../../../src/journeyplus/agent/services/completion.py:147)。
- **整改方向**：将可验证的事实/操作/展示结果绑定真实引用与回执，让用户界面的完成状态来自实际结果；为对象提供可读渲染，避免原始 JSON。保留自然语言解释和模型自主决策，不能为了“保证”加入固定业务流程、关键词授权器或隐藏裁判模型。请求覆盖和自由文本语义仍需人工/真实模型场景审计，不能声称任意模型都会完美。

### A8 · 测试口径与运行工具定义不一致

- **事实**：本轮 115 项辅助检查中 114 通过，`test_tools_schema_budget` 用原始 Pydantic schema 得出估算 8046，断言 `<8000` 失败；实际注册工具 schema 已去除标题，含描述估算 7593，注册和问候上下文投影均通过。native wire 工具定义紧凑序列化 23218 字节，按估算器口径为 8354；不是提供方实际 token。
- **影响**：现有测试不是绿色；但不能将该失败说成正常服务必然无法启动，也不能拿内部估算代替单次真实消耗。
- **依据**：目标 §4、§8；[test_harness_contracts.py:51](../../../../tests/test_harness_contracts.py:51)、[registry.py:18](../../../../src/journeyplus/agent/harness/registry.py:18)、[model.py:147](../../../../src/journeyplus/agent/adapters/model.py:147)。
- **整改**：分别验证内部契约预算、实际 wire 预算和提供方实测，不简单增大上限“修绿”。同一场景先证实效果，再减少重复内容。

### A9 · 项目运行残留和说明尚未收敛

- **事实**：PostgreSQL 有 224 个 JourneyPlus 命名库（正常 1、eval 209、其他项目历史/修复/恢复 14），合计约 **6.92 GiB**；另有系统库 `postgres`，不属于清理对象。`.secrets` 中 10 个项目证据/备份/服务日志目录合计约 242.6 MiB。仓库保留 17 个阶段脚本、旧运行说明和旧产品模式；暂停自动化文本仍要求三来源，库内实际自动来源为两项。
- **影响**：若不核对用途和入口，易再次误用临时库/旧命令。目录存在本身不是当前服务错误；备份和本地测试临时库也不是天然“坏架构”。
- **依据**：目标 §6、§7；repository/runtime-baseline/runtime-http 证据，下面逐项处置表。
- **整改**：区分正常运行、必要测试、仅供恢复和已无用途的资源，核实依赖后清理；唯一启动/运维说明指向目标结构。不删其他项目/系统数据库、不删除凭证，不重写 Git 历史。旧 change 按用户要求暂不处理。

## 5. 尚不能判为缺陷、但必须验证的事项

- **上下文**：`harness/context.py` 按整组保留调用/结果、去重并保留展开引用，已有合理能力。`load_context_index()` 每次读取全部会话，再按容量/12 条可见消息选择近期历史；旧约束仅可检索、任务笔记非强制。长期性能和跨裁剪后的约束保持是需覆盖的风险，不能仅凭代码推断每轮都丢记忆。本轮没有调用真实模型测 token。
- **授权**：逐字引文和消息归属校验能证明引用来自用户，不能独立证明引文含义授权了某项动作。现有代码保留 `interpretation_verified=false` 是诚实边界；不把它误写成数据库可自动验证全部自然语言意图。
- **目录等价**：代码有有证据的名称等价规则。本轮按现有 `program_key` 未找到重复项目组，不能宣称正常库中必有同义项目重复。后续仍应把可维护的别名/来源元数据归到目录生产职责，避免越积越多品牌补丁。
- **知识可用性**：`availability()` 仅检查目录和已发布版本非零；它有价值，但不能证明目标活动、全部来源、简报和图已完整。查询已带多种覆盖字段，交付页面应保持这些区别。
- **模型配置**：AgentConfig 与 Workflow 配置分开，替换 Agent 模型不会改 Workflow 配置。Workflow `Settings.require_ai()` 仍将模型锁为 deepseek-v4-flash，后续可按用户授权取消不必要型号限制；这不等于 Agent 与该型号强绑定。
- **独立买分功能**：`buy_points` 没有导入会籍/文章业务模块，仍有 CLI、两张表和手工用途；属于目标核心之外的现存功能，不能仅因非核心就标为死代码并删除。最终是否保留入口需明确产品范围。

### 上下文与数据读取的后续优化候选

这些是代码可见的重复工作，不是本轮已优化或已实测的收益：

1. `context.project()` 对 3 个知识工具分别调用同一个 `KnowledgePort.availability()`，每次各查项目/等级/发布数；可以在单次请求内共享同一就绪观察，保留下一次请求重新检查的能力。
2. `load_context_index()` 总是从数据库读取全部会话；运行循环再次读取它时主要需要 state，随后又在 Python 压缩模型输入。可分离状态读取、近期调用组与按需历史检索，前提是完整保留有效约束与原话访问。
3. 12 个工具 wire 定义每次请求重复携带，文本较长；先统一预算测量口径，再精简重复解释/结构。不能为省 token 隐藏可用能力或限制模型自主选工具。
4. Workflow 提取会带全量目录，并先跑旧事实/简报生产。先消除 A2 的重复生产，之后测量相关目录渐进披露；不能把 Workflow 的输入开销误算成 Agent 每轮记忆开销。

## 6. 模块职责、输入输出与处置

下表是人工核对的模块级地图。逐文件导入与定义见 source-map，逐表消费者见后续表清单；同一模块有多种用途时分别处理，不能整目录无条件删除。

| 模块/入口 | 输入 → 输出；主要消费者 | 处置 |
|---|---|---|
| `sources/*`、`content/*` | 邮件/网页/订阅 → sources/source_items/document_versions；Workflow 使用 | 保留采集与正文能力；来源策略与一次性初始化分离 |
| `statusmatch/watchlist,monitoring,fetching,service,closure` | 邮件项目链接、三页资料 → watch/page/文档状态与关闭证据 | 保留职责；watch 的活动身份改为目标契约 |
| `statusmatch/project_workflow` | 文档 → 旧 fact_sets/briefs，供 refresh 与旧消费 | 改造输出为目标草稿/发布，复用来源校验与表格解析 |
| `statusmatch/articles,article_workflow,article_contracts` | 相关文章 → 项目关联/补充旧简报 | 保留有依据的文章关联；改为统一证据/草稿，不保存第二套正式摘要事实 |
| `statusmatch/graph,graph_contracts,audit,composed_brief` | 旧事实图/旧简报 → CLI、review、旧产品 | 消费者迁出后退出旧表示，保留可复用核对算法 |
| `article_operations`、`article_pipeline/*` | 标题/正文 → 分类、文章活动、旧简报和生命周期 | 保留筛选/拆分/原文审核，收敛单一草稿和发布；淘汰旧产物消费 |
| `workflow.py,status_topic,clustering,facts,briefs,lifecycle` | 早期通用流水线与确定性事实工具 | 分拆处置：旧通用权威链在消费者迁出后退出，表格/费用/规范化/时间算法保留 |
| `knowledge/refresh,workflow,publication,identity,edition_guard` | 文档绑定/草稿 → 正式版本与期次 | 核心保留改造；去迁移身份依赖、补发布门槛与正式初始化入口 |
| `knowledge/models,contracts,sources,table_groups` | 契约、章节、证据、确定性映射 | 保留共享数据契约/生产能力；依职责组织，不重复建设 |
| `knowledge/access,reads,routes,selection,cards,briefs` | 正式知识 → 查询、图、卡片、简报 | 保留；查询/展示共同语义，产物绑定发布版本 |
| `knowledge/temporal,countries,regional_prices,price_quarantine,catalog_*` | 带证据字段 → 确定性语义/校验 | 保留正确算法；目录元数据整理归生产方，不做单模型补丁 |
| `knowledge/migration,holding_migration,compatibility` | 旧身份、旧记录 → 回填/兼容映射 | 当前仍有消费者，替换后删除运行兼容；恢复记录不等于兼容模块 |
| `knowledge/packets,transport,references,pagination,token_budget` | 旧/共享 DTO、引用、范围 → 模型/图传输 | 逐导出核对；`routes.py` 仍调用 transport，不能整包删。保留分页/引用和查询契约，退出旧专属 packet 分支 |
| `membership/normalization,alliances,contracts,traversal` | 名称、图贡献 → 标准身份/确定性遍历 | 复用纯能力；剥离只服务旧 DTO 的部分 |
| `membership/contributions,unified` | 旧官方/文章事实 → 旧图，供产品、CLI、review | 对齐新查询后退出旧消费，不再双图真值 |
| `agent/harness/*` | 模型请求、工具响应 → 通用运行/预算/事件 | 保留；补同链路观察能力及上下文可验证性 |
| `agent/adapters/*` | 协议/存储/外部服务 → ports | 保留；删除历史导入兼容，明确配置和审计；不能整删持久化/幂等 |
| `agent/tools/*` | 显式参数 → 目录/活动/路线/研究/操作/展示结果 | 保留独立工具；结果语义和调用错误以真实网页验收 |
| `agent/services/*` | 知识、用户数据、快照 → 查询/记忆/展示/等待 | 保留职责；补交付证据，避免工具间隐藏编排 |
| `agent/composition,server,instructions` | 配置/依赖/提示 → Agent 装配 | 保留；接网页人工 ModelPort，运行指纹与代码一致 |
| `product/agent_api,agent_lifecycle`、`workspace_v3.*` | 网页 → run/SSE/取消/恢复 | 保留；退出旧 workspace 路由/导入，验证真实展示及状态 |
| `product/knowledge_public_api,knowledge_server`、knowledge/explore 静态页 | 正式数据 → 独立知识页面/图 | 保留；从“预览/过渡”收敛到正常入口，移除 legacy 映射 |
| `product/api,rollout,knowledge_api,holdings` | 新旧 API 装配、旧/新会籍读写 | 拆出必要用户服务，统一正式入口，去 legacy/unified/rollback 消费切换 |
| `product/opportunities,briefs,candidate_routes`、`static/app.*` | 旧 DTO/旧图 → 历史产品页面 | 消费者退出后删除或替换；不保留另一套推荐结果 |
| `review/*` | 旧事件/事实 → 人工审核与改写 | 审核能力归 AIWorkflow；改为目标草稿/期次/证据契约后退出旧事件 API |
| `automation/*`、`jobs/*` | 调度/初始化/重试 → 处理状态 | 保留；统一目标发布状态、通用初始化清单和最终写入暂停方式 |
| `config.py,db.py,models.py,workspace_models.py`、迁移 | 配置/元数据 → 连接、表与运行结构 | 保留基础设施并按所有权整理；公共 Base/JSON 类型不应从业务域倒借 |
| `ai/*` | Workflow 请求 → 模型响应 | 保留与 Agent 分开的提供方职责；取消不必要型号钉死 |
| `buy_points/*` | 单页 → 买分数据/CLI | 有实际消费者，范围待定，不能认作 Agent 旧控制器 |
| `evaluation/*,gold/*,tests/*` | 固定样本/测试 → 辅助证据 | 保留必要回归，淘汰过时手工金标流水线；不能向正常库灌固定答案替代重建 |


## 7. 全部物理表的去留与退出依赖

这是审计后的处置方向，**不是可立即执行的 DROP 清单，也不是已冻结最终 DDL**。当前字段/约束/索引全部见 database-schema。下列“保留”不表示保留旧数据；旧知识按未来清理清单重建。个人数据另行明确。

### 基础与来源（保留职责）

| 表 | 当前行数 | 主要直接消费者（示例） | 处置与理由 |
|---|---:|---|---|
| `alembic_version` | 1 | Alembic/元数据；见字段与调用索引 | 保留唯一目标版本标识；空库最终不能仍创建已退出的旧表。 |
| `collection_runs` | 55 | `automation/initialization.py`, `automation/rebuild.py`, `automation/service.py` | 保留采集状态与实际范围。 |
| `document_sections` | 4944 | `knowledge/edition_guard.py`, `knowledge/publication.py`, `knowledge/reads.py` | 保留正文/表格的精确定位；ROW 与 TABLE 是层次结构，不以文本重复就判冗余。 |
| `document_versions` | 214 | `article_operations.py`, `article_pipeline/evaluation.py`, `article_pipeline/interpretation.py` | 保留不可变原文、规范正文、哈希与时间；清旧数据不删源邮箱邮件。 |
| `evidence_references` | 697 | `knowledge/identity.py`, `knowledge/price_quarantine.py`, `knowledge/publication.py` | 保留来源定位和逐字证据；不把引用存在等同语义支持。 |
| `source_items` | 160 | `article_operations.py`, `article_pipeline/interpretation.py`, `article_pipeline/phases.py` | 保留真实邮件/URL 身份、发表时间和采集状态。 |
| `sources` | 9 | `automation/rebuild.py`, `automation/service.py`, `evaluation/runtime.py` | 保留来源配置；一次性清单不写成长期来源禁用。 |

### 任务与生产审核（整理契约）

| 表 | 当前行数 | 主要直接消费者（示例） | 处置与理由 |
|---|---:|---|---|
| `activity_edition_reviews` | 0 | `knowledge/edition_guard.py`, `knowledge/identity.py` | 保留期次审查；source_table/source_id 不再只允许两种旧业务表，改为明确来源身份。 |
| `analysis_runs` | 356 | `article_pipeline/briefs.py`, `article_pipeline/interpretation.py`, `article_pipeline/phases.py` | 保留提取与分类执行记录；event_id 外键退出旧 status_events，结果明确为草稿。 |
| `article_analyses` | 62 | `article_operations.py`, `article_pipeline/briefs.py`, `article_pipeline/interpretation.py` | 保留分类/拆分的处理记录；analysis_run/document/source 关系继续可追溯。 |
| `article_opportunities` | 23 | `article_operations.py`, `article_pipeline/briefs.py`, `article_pipeline/interpretation.py` | 改成有范围的活动草稿/来源关联，退出旧 current brief、legacy 业务生命周期及权威事实消费。可重命名，不能仅改表名。 |
| `automation_leases` | 1 | `automation/rebuild.py`, `automation/service.py` | 保留调度互斥；清库前必须核对所有写入者，不只租约。 |
| `automation_runs` | 10 | `automation/rebuild.py`, `automation/service.py` | 统一目标发布/简报/失败计数与来源范围。 |
| `initialization_runs` | 1 | `automation/initialization.py`, `automation/rebuild.py` | 保留批次状态，移除固定历史日期与旧产物完成标准。 |
| `job_runs` | 321 | `article_operations.py`, `automation/rebuild.py`, `automation/service.py` | 保留幂等/错误/重试，工作类型改为最终生产阶段。 |
| `review_decisions` | 0 | `article_operations.py`, `automation/rebuild.py`, `review/service.py` | 改为目标草稿/正式期次/证据审核，记录明确对象，不继续修改旧事件事实。 |
| `source_automation_states` | 7 | `automation/rebuild.py`, `automation/service.py`, `sources/collection.py` | 重建后新的增量边界；不能旧 cursor 导致漏重读邮件。 |
| `statusmatch_article_routes` | 2 | `membership/contributions.py`, `product/opportunities.py`, `statusmatch/article_workflow.py` | 必要文章到活动关联改用正式身份；不以旧 event_id 永久桥接。 |
| `statusmatch_watch_pages` | 21 | `knowledge/refresh.py`, `statusmatch/articles.py`, `statusmatch/audit.py` | 保留同一项目三页版本及检查状态。 |
| `statusmatch_watches` | 7 | `automation/rebuild.py`, `knowledge/refresh.py`, `product/opportunities.py` | 保留来源监控；current_event_id 改为正式活动/来源绑定，需完成身份契约。 |

### 正式知识与产物（保留改造）

| 表 | 当前行数 | 主要直接消费者（示例） | 处置与理由 |
|---|---:|---|---|
| `activities` | 8 | `agent/services/snapshots.py`, `agent/tools/knowledge.py`, `knowledge/catalog_metadata.py` | 保留稳定活动身份/期次/当前指针；去 legacy identity 生产依赖。 |
| `activity_briefs` | 8 | `knowledge/briefs.py`, `knowledge/publication.py`, `knowledge/reads.py` | 保留版本派生产物；调整先准备后发布，避免 pending brief 已切当前版本。 |
| `activity_documents` | 22 | `knowledge/catalog_metadata.py`, `knowledge/edition_guard.py`, `knowledge/publication.py` | 保留正式版本与来源绑定；不能代替尚未发布活动的身份发现契约。 |
| `activity_knowledge_versions` | 8 | `agent/services/snapshots.py`, `knowledge/access.py`, `knowledge/briefs.py` | 保留不可变事实、base/extraction/fact/source 哈希；发布状态需绑定必要产物就绪。 |
| `activity_observation_state` | 8 | `agent/services/snapshots.py`, `knowledge/reads.py`, `knowledge/refresh.py` | 保留最新检查/失败/新鲜度，区别事实版本。 |
| `application_option_versions` | 16 | `agent/services/snapshots.py`, `knowledge/publication.py`, `knowledge/reads.py` | 保留单版本方案事实和活动/版本组合外键。 |
| `application_options` | 16 | `knowledge/publication.py`, `knowledge/workflow.py` | 保留跨版本的方案身份。 |
| `membership_aliases` | 22 | `agent/services/identities.py`, `agent/services/snapshots.py`, `agent/tools/knowledge.py` | 保留别名与出处，生产时整理身份；前端/Agent 共用。 |
| `membership_programs` | 128 | `agent/services/identities.py`, `agent/services/route_query.py`, `agent/services/snapshots.py` | 保留规范项目和有出处元数据。 |
| `membership_tiers` | 433 | `agent/services/identities.py`, `agent/services/snapshots.py`, `agent/tools/knowledge.py` | 保留项目内等级及组合约束，不将相似级别误合并。 |
| `option_mappings` | 591 | `knowledge/publication.py`, `knowledge/reads.py`, `knowledge/routes.py` | 保留明确来源→目标和条件，不把全部项目类别当具体映射。 |
| `option_price_mappings` | 6 | `knowledge/publication.py`, `knowledge/routes.py` | 保留显式收费适用映射关系。 |
| `option_prices` | 35 | `knowledge/publication.py`, `knowledge/reads.py`, `knowledge/routes.py` | 保留未知、币种、范围、条件、收费角色；不能为省表将关系压成自由文本。 |

### 用户与 Agent（保留职责、移除历史兼容）

| 表 | 当前行数 | 主要直接消费者（示例） | 处置与理由 |
|---|---:|---|---|
| `agent_artifacts` | 142 | `agent/adapters/artifacts.py`, `agent/adapters/persistence.py`, `agent/adapters/workspace_writes.py` | 保留结果/展示快照和证据引用，生命周期与恢复明确。 |
| `agent_delivery_events` | 262 | `agent/adapters/models.py`, `agent/adapters/persistence.py` | 保留可重放 SSE/展示事件，不将事件成功当用户目标成功。 |
| `agent_delivery_runs` | 14 | `agent/adapters/models.py`, `agent/adapters/persistence.py` | 保留实际运行/取消/状态；补部署指纹与观察关联。 |
| `agent_interactions` | 10 | `agent/adapters/artifacts.py`, `agent/adapters/persistence.py`, `product/api.py` | 保留会话实体；去旧 schema/state/last_response 导入分支，清理字段要依新会话消费者。 |
| `agent_operation_receipts` | 0 | `agent/adapters/persistence.py`, `agent/services/user_memory.py`, `agent/services/waiting.py` | 保留跨会话寿命的实际写回执；无强级联是有用途的，不误判孤儿。 |
| `agent_run_checkpoints` | 14 | `agent/adapters/persistence.py`, `agent/adapters/transactions.py` | 保留恢复/累计预算；另补有范围的单次模型请求观察。 |
| `agent_tool_calls` | 61 | `agent/adapters/persistence.py` | 保留参数/效果/状态与结果引用，支持同轮追踪。 |
| `agent_turns` | 14 | `agent/adapters/persistence.py` | 保留轮次、幂等与状态。 |
| `agent_wait_goals` | 1 | `agent/services/snapshots.py`, `agent/services/waiting.py`, `knowledge/user_journal.py` | 归用户业务数据，保留独立确定性检查；去旧研究/控制器字段前核对 WaitingService 使用。 |
| `agent_workspace_messages` | 161 | `agent/adapters/persistence.py`, `agent/adapters/workspace_writes.py`, `agent/services/user_memory.py` | 保留原话、调用与结果，受会话作用域约束。 |
| `status_holdings` | 2 | `agent/adapters/user_data.py`, `agent/services/snapshots.py`, `agent/services/user_memory.py` | 保留实际会籍、未解析姓名与原话出处、revision；不能因无目录ID就删用户表达。 |
| `user_business_operations` | 0 | `knowledge/user_journal.py` | 保留有明确恢复用途的业务日志；退出旧 payload 补字段兼容，不当聊天记忆。 |

### 旧权威事实及兼容（依赖退出后删除）

| 表 | 当前行数 | 主要直接消费者（示例） | 处置与理由 |
|---|---:|---|---|
| `article_briefs` | 23 | `article_pipeline/briefs.py`, `article_pipeline/phases.py`, `article_pipeline/read_model.py` | 文章目标简报发布接管后删除。 |
| `briefs` | 68 | `automation/rebuild.py`, `briefs/service.py`, `product/briefs.py` | 正式版本简报取代后删除旧模型简报。 |
| `event_evidence` | 30 | `automation/rebuild.py`, `clustering/aggregator.py`, `clustering/relationship.py` | 正式 activity_documents/evidence_references 接管后删除。 |
| `event_revisions` | 17 | `automation/rebuild.py`, `clustering/aggregator.py`, `facts/service.py` | 事实演进由正式版本/处理记录承担后删除旧演进链。 |
| `fact_sets` | 66 | `automation/rebuild.py`, `automation/service.py`, `briefs/service.py` | StatusMatch 提取直接产出目标草稿后删除旧权威事实。 |
| `knowledge_migration_links` | 1147 | `knowledge/compatibility.py`, `knowledge/identity.py`, `knowledge/migration.py` | 生产身份、期次合并记录及 legacy URL 消费全部迁出后删除。 |
| `status_events` | 8 | `automation/rebuild.py`, `automation/service.py`, `briefs/service.py` | 替换生产身份和所有消费后删除；不能本轮直接删。 |
| `statusmatch_article_supplements` | 16 | `statusmatch/article_workflow.py`, `statusmatch/composed_brief.py` | 第三方证据/草稿及统一简报接管后删除旧简报补丁。 |
| `statusmatch_change_sets` | 49 | `statusmatch/audit.py`, `statusmatch/project_workflow.py` | 正式版本差异/更新简报接管后删除旧 fact-set 差分链。 |

### 非核心/验收专用（范围待定）

| 表 | 当前行数 | 主要直接消费者（示例） | 处置与理由 |
|---|---:|---|---|
| `buy_points_offers` | 65 | `buy_points/service.py` | 同上，与 snapshot 的真实子记录关系保留至范围明确。 |
| `buy_points_snapshots` | 4 | `buy_points/operations.py`, `buy_points/service.py` | 手工买分功能仍消费；先明确范围，不能按废表删除。 |
| `gold_cases` | 0 | `automation/rebuild.py` | 当前 0 行，评价用途应离正常产品 schema；核对 evaluation/review 消费后退出。 |

### 最终结构需要进一步冻结的部分

活动/方案/版本/映射/价格/证据的现有结构大体可复用，不需要推倒重建。必须补明白的是：未发布活动的来源身份与文章拆分关联、处理中间草稿、期次审核引用、发布产物就绪、会话/业务操作分域。优先复用改造现有生产记录；只有现有表不能表达一个必要独立职责时才新增表。
下一阶段将上述方向写成最终字段与键约束、迁移基线和精确删除顺序；此处不假装已经完成 `tasks 1.5`。尤其原始文档、必要草稿和操作回执不是应删除的兼容残留。

## 8. 脚本、文档与临时资源

### 17 个脚本逐项处置

| 脚本 | 实际用途 | 目标处置 |
|---|---|---|
| `audit_agent_context.py` | 离线回放上下文、字节/估算统计 | 保留辅助分析，接真实 wire 记录；不能替代真实 token |
| `review_agent_harness.py` | 隔离库 stdin 人工 ModelPort | 合并/改造为正常网页 ModelPort 接入；现状仅诊断 |
| `evaluate_agent_harness.py` | 隔离库真实模型回归 | 可保留辅助回归，补自动资源回收；系统验收另走正常网页 |
| `evaluate_packet_formats.py` | 旧/紧凑/分页 packet 格式对比 | 随旧 packet 消费退出而收敛，保留有依据的测量逻辑 |
| `migrate_agent_evaluation.py` | 显式 eval 库升级 | 必要测试工具可保留/合并；不是正式库启动入口 |
| `compare_knowledge_reads.py` | 新旧读取影子对比 | 无旧数据兼容目标下，完成消费者核对后退出 |
| `promote_knowledge_snapshot.py` | 从副本向空知识库复制已审核知识 | 本次重建禁止用来替代真实生产，目标入口退出该晋升路径 |
| `export_validation_snapshot.py` | 导出公开知识作为固定回归样本 | 可保留测试用途，改为目标 schema；不导入正常库 |
| `user_operation_journal.py` | 明确操作日志导出/冲突安全回放 | 保留有用途的恢复能力，去旧结构兼容；不得作为记忆来源 |
| `verify_user_journal_postgres.py` | 隔离库验证日志恢复 | 保留 PostgreSQL 恢复验证，结束后处理临时库 |
| `smoke_public_sources.py` | 公开来源只读抓取诊断 | 保留需要的诊断；来源清单以正常配置为准 |
| `collect_real_lifecycle_cases.py` | 固定旧年份 URL 的生命周期样本采集 | 从正常维护入口退出；保留必要离线案例，不能用于重新生产当前知识 |
| `build_phase1_gold.py` | 早期金标资料抓取/组装 | 现有阶段产物固定后退出一次性生成脚本，不再混入正常启动 |
| `build_phase1_gold_zh_review.py` | 金标翻译/复核生成 | 同上；可复用通用检查代码不等于保留整套旧流程 |
| `revise_phase1_gold_v2.py` | 一次性金标修订 | 依赖核对后退出 |
| `revise_phase1_gold_v3.py` | 一次性金标修订 | 依赖核对后退出 |
| `revise_phase1_gold_v4.py` | 一次性金标修订 | 依赖核对后退出 |

### 文档、配置与迁移

- 本轮核心为本 change 的 target-architecture；README 顶部已指向新目标，但下面仍保留大量历史命令/描述，已标为历史说明。最终交付需重写正常运行部分，不能留一个新标题却继续指导运行旧入口。
- 旧 OpenSpec change、旧审计及其 17 个历史改动不纳入本轮修改；现存旧文档只作核对线索。没有把旧结论复制成新的问题依据。
- 28 个迁移版本描述早期至当前 schema；目标空库不能升级后还保留待退出表。需决定新的目标基线与迁移组织，保留有用历史依据不等于要求运行旧数据兼容。
- `pyproject.toml` 的 3 个入口包含主 CLI、评估 CLI、旧 gold runtime；评估用途应清晰隔开，正常启动只讲当前目标路径。`.env` 不入版本控制；审计只保存允许披露的配置项，没有保存 API key、数据库密码或邮箱令牌。
- Codex 每日自动化当前暂停，其文字与数据库来源配置不一致；未来恢复前更新为最终生产入口和来源策略。本轮没有改动自动化。

### 项目数据库和文件资源

所有数据库名称和大小在 runtime-baseline 中逐项列出；处置建议如下，实际删除仍需一次明确的执行清单：

| 资源 | 处置依据 |
|---|---|
| 正常 `journeyplus` | 本轮只读审计；以后停写、备份恢复验证、明确个人数据范围后重建 |
| 209 个 `journeyplus_eval_*` | 阶段测试副本；按具体名称、证据关联与活动连接确认后清理，未来测试生命周期自动回收 |
| `journeyplus_knowledge_*`、`journeyplus_normal_*` | 旧验证/修复/晋升副本，不能继续冒充正常库；核对需保留的恢复证据后退出 |
| `journeyplus_restore_*` | 恢复演练副本；恢复校验所需证据保留，运行副本不长期并行 |
| `journeyplus_expiry_*`、`journeyplus_migration_*`、`journeyplus_real_*` | 历史过期、迁移和生命周期验证资源；完成证据/用途核对后清理 |
| 系统库 `postgres` | 不属于 JourneyPlus 业务清理范围 |
| `.secrets/agent-harness`、`agent-repair`、`knowledge-validation` 等阶段证据 | 保存必要失败/验收证据；多余导出按用途清理，不成为运行依赖 |
| `.secrets/architecture-restart`、`backups` | 已知恢复用途，先明确恢复保留条件，不作为旧结构长期兼容理由 |
| `.secrets/service-logs`、正常网页/失败审计目录 | 保留本次问题定位所需日志，后续有明确保留/清理边界 |
| `.venv`、Python/pytest 缓存、凭证配置 | 开发环境/凭证不同于旧业务残留；不靠清空它们“清理架构” |

## 9. 建议的实际改造顺序与阶段产出

1. **冻结具体设计**：以本次调用链/全表表格为基础，确定最终来源身份/草稿/发布契约、字段与约束、模块所有权及精确删除顺序。优先迁出 A2/A5 中仍使用旧表的消费者，不先删表再追报错。
2. **冻结清理范围**：明确个人数据、初始化来源/GHA 对象、买分功能处置、恢复保留范围；核对写入者并验证恢复。此时才可以停写清库。
3. **实现目标代码**：生产直接输出目标契约，简报/图准备后统一发布；旧读取/导入/切换退出；正常入口与模型/工具观察完善。旧正确算法、harness/工具持久化继续复用。
4. **从空库重新生产**：最终 DDL 建库，邮件/StatusMatch/当日 LoyaltyLobby 经正常 Workflow 入库；核对来源和产物，不复制现有 eval/修复库数据。
5. **正常网页两轮验收**：先人工 ModelPort 双视角、再经济型第三方 Agent 模型；后续按实际 token 和结果做上下文优化及复验。

### 下一步验收场景的审计补充

既有 acceptance.md 矩阵继续有效，依据本轮新增以下必测输入/故障条件：

- 用户原始失败句：“我有万豪白金，我想要所有匹配的可能”；从正常网页发起，第一视角不能偷看数据库补条件，核对全部分页与正式图。正确候选清单应在**重新生产后的来源版本**上建立，不能把当前 23 条冻结为永久答案。
- 多轮：“先只看明确免费”→“现在不限费用，但还从万豪白金出发”→“把两条路径比较一下”；不得把上轮目标当新起点，保持版本与费用范围。
- 假设会籍、明确不保存、明确授权保存/修改/删除、写后取消/断连；真实写入主体先明确，不能拿现有两条会籍演练。
- 来源已采集但未发布、简报生成失败、三页缺失、未知费用、旧版本简报链接；检查不能把空/未知/未就绪混为没有机会。
- 同一模型请求在人工与提供方端的输入/工具定义/返回一致；端口配置切换不另建产品或数据库。
- 长历史裁剪前的有效条件、纠正和写入回执；对比模型实际输入及可展开资料，不仅看持久化全文还在。

这些是具体场景草案；最终来源预期、重复次数、写入主体尚未冻结，`tasks 1.6` 不勾选。

## 10. 本轮完成与明确未做

完成任务 **1.1—1.4**：运行基线、模块与表映射、数据库/资源清点、对照规格的差距及反证。**1.5 为设计输入已齐、最终 schema/精确删除顺序未冻结；1.6 为场景补充完成、验收基线和写入主体未冻结。** 后续清理、实现、生产、人工验收、真实模型验收仍未开始。

本轮未修改业务源代码或旧 change，未删除数据库/文件，未重启正常服务，未采集外部来源，未调用第三方模型，未创建 Git 提交。网页自动创建空工作区的副作用已在 §2 单独记录。审计文档、机器证据及任务状态留在工作区。

辅助验证命令是 `.venv/bin/python -m pytest`，仅选择 architecture、agent_workflow_isolation、harness_contracts/audit_boundaries/context/memory/recovery、knowledge_independent_api/workflow_boundaries/refresh/pagination、agent_completion、product_startup、agent_readiness_failure 这 14 个文件；测试用 SQLite 临时夹具和 fake provider，不是正常 PostgreSQL 网页验收。完整结果见 local-checks；未在发现一个失败后随意改实现让它通过。
