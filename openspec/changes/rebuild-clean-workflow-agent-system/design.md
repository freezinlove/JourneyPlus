## Context

历史实现中哪些部分符合目标、哪些需要退出，须以当前仓库和实际运行数据为依据重新审计。本设计描述目标，不将历史问题编号、测试通过数量或旧方案的勾选作为事实证明。总体边界以 [目标架构](target-architecture.md) 为准。

## Goals / Non-Goals

目标是让知识生产与 Agent 消费独立，以同一数据库中的正式知识契约联通，并在最终正常网页证明端到端功能可用。代码、脚本、配置及物理数据结构均应有明确职责和消费者。

本次不引入微服务拆分、额外业务数据库、固定 Agent 业务流程、品牌专属修补或旧数据兼容层。不因追求“全新”重写已有正确算法，也不把 AIWorkflow 或必要处理中间记录当作应删除的旧链路。

## Decisions

### 1. 按数据所有权划分两个板块

AIWorkflow 拥有采集、文档整理、身份与事实提取、校验及统一发布。Agent 通过稳定查询接口读取正式知识，通过用户数据服务处理显式授权操作。公共契约、存储、确定性查询与图算法是共享能力，不是第三套业务编排。

装配层可以在一个进程内提供两个板块的路由；业务模块不得通过装配层形成反向依赖。物理目录按现有合理实现选择，审计先给出模块—入口—输入输出—消费者—表映射，随后决定移动、合并、保留或删除。

### 2. 一个正式知识契约，允许必要生产阶段

逻辑数据域包括来源与处理记录、会员目录、正式知识、版本简报/必要图索引、用户业务数据、Agent 会话。审计将其映射到最终表、键、约束、索引与读写方，说明每个中间产物的用途。

原始文档与草稿不直接作为正式事实。活动期次、来源版本、方案、映射、费用、条件和证据应保持关联；未知、冲突和不适用分别表达。禁止以长期双写、同义事实转换或旧查询回退维持第二套权威结构。查询只披露任务所需信息，并提供稳定引用及展开能力。

### 3. 校验后短事务发布，产物绑定版本

网络采集和模型处理在发布事务之外执行。事实、必要简报和图数据校验通过后，短事务切换可消费版本；失败保留可解释状态和上个有效版本。来源未变化时可幂等复用；变化则产生新版本，历史简报引用不随当前指针漂移。

完整匹配图由正式事实及共享确定性算法产生，可按需计算或保存版本缓存，不能独立修改为另一套真值。知识页面不依赖 Agent 模型；Agent 的路径选择与完整图遵循相同条件和费用语义。

### 4. 通用 harness 与可观察 ModelPort

Harness 管理模型/工具协议、循环、预算、取消、恢复和记录；不导入业务 ORM，不决定常旅客业务步骤。工具参数显式、输出有范围和错误语义，工具之间无隐藏业务编排。模型决定是否调用、调用顺序和如何解释；适配器只处理提供方协议差异。

人工接入只替换正常服务的 ModelPort 决策端，用户输入仍从正常网页进入。人工端收到与模型端同构的真实请求，提交相同类型的文本/调用响应；不能预先查询数据库再代模型选择答案。第三视角在事后关联同一轮证据，不将审计信息偷偷补入模型上下文。

观察能力记录版本、请求、模型可见消息/工具定义、工具参数/返回、状态变化、数据库回执和页面结果。敏感配置不写入证据，审计载荷限定本次验收用途，不默认永久记录所有个人对话。输出缓冲或流式策略须在页面显示真实进度、错误和取消状态；不能以一个 COMPLETED 字段代替实际交付。

### 5. 正确性先于上下文压缩

区分用户原话、真实会籍、假设、工具事实和模型笔记。渐进披露保留来源、范围、未读页、条件未知和稳定展开引用。压缩不得吞掉有效约束、纠正、操作回执或续读位置；工具重试不能重复副作用。

先记录单次请求与整轮 token、重复工具结果、调用次数和延迟，再针对真实冗余做优化。优化前后使用相同知识版本和场景核对答案、行动、覆盖及证据，不以缩短字符串或提高预算证明改善。

### 6. 有边界的清理与空库重建

先冻结实际清单、恢复办法和最终 schema，再停止页面写入、采集、调度与其他后台写入者；验证备份可恢复后执行清理。架构调整期间保持旧写入停止。物理旧表的退出时间依赖消费者改造完成，不在代码仍依赖时盲删。

个人会籍/会话/操作记录的处置单独明确，源邮箱邮件不删除。项目临时库按归属和用途核对后清理，不按通配符删除其他项目数据库。恢复备份在正常入口之外，有用途与清理条件；不为恢复引入运行兼容层或重写 Git 历史。

从空库创建目标结构，再由正常 AIWorkflow 重读邮件、获取 StatusMatch 官方资料和重建当天最新 LoyaltyLobby 文章。执行前记录日期、时区、来源选择与本次 GHA 排除对象；一次性清理不变成滚动十天、永久黑名单或未来禁采规则。初始化不能复制旧测试事实，也不能伪造缺失数据。

### 7. 验收以最终服务为准

单元测试、隔离库、直接工具脚本只证明局部性质。系统验收必须走同一正常网页、API/SSE、harness、工具和数据库，分别检查用户实际看到什么，以及背后实际发生什么。

先通过生产链与人工 ModelPort 双视角检查，才开始 Agent 第三方模型验收。为重建知识而调用 AIWorkflow 的提取/简报模型属于生产阶段，须单独记录模型与消耗，不能冒充 Agent 验收。当前创建方案不调用任何模型；后续使用已授权的经济型模型，不使用 Max 类型号。

## 审计后的实施结构冻结（任务 1.5，2026-09-09）

以下是待实现的具体设计，不是当前系统能力声明。依据为 [审计 A1–A9 与全表/消费者地图](audit/report.md)。未列出变更的字段、类型、空值、默认值、主键、外键、唯一约束和索引，逐项沿用本 change 内的 [物理 schema 快照](audit/evidence/database-schema.json)；下列增删替换覆盖该基线。这样既明确最终结构，也不复制一份容易漂移的完整字段字典。任何新增差距必须补证据和设计，不能在实施中悄悄扩大范围。

### A. 模块落位与允许依赖

| 模块位置 | 唯一职责与依赖 |
|---|---|
| `db.py`、新增 `storage/base.py`、`storage/metadata.py` | 连接、公共 Base/时间/JSON 类型、完整模型注册。注册由装配/迁移调用；业务模型不循环导入其他板块来注册元数据 |
| `sources/`、`content/`、新增 `sources/models.py` | 来源配置、采集、不可变文档及采集记录；输出文档 ID/哈希，不输出另一套业务事实 |
| `automation/`、`jobs/`、各自 `models.py` | 调度、批次、重试与写入暂停；调用 Workflow 的明确入口，不调用 Agent 决策循环 |
| `statusmatch/`、`article_pipeline/` | 来源特有的发现、监控、筛选、拆分、精确章节/表格识别；输出下文的发现与来源计划契约 |
| `knowledge/workflow.py`、`refresh.py`、`identity.py`、`publication.py`、`briefs.py` | AIWorkflow 的统一知识生产应用层：身份、草稿、校验、简报准备与发布。不依赖 Agent |
| `knowledge/models.py`、`contracts.py`、`reads.py`、`routes.py` 等 | 共享知识结构、只读契约和确定性算法。读模块不能反向调用生产入口；生产与消费可共用纯算法 |
| 新增 `user_data/models.py`；现有用户服务/适配器 | 会籍、等待任务、业务日志与持久回执的所有权。保留现有事务/授权/幂等服务，页面与工具共用，不另写 CRUD |
| `agent/harness/`、`agent/adapters/`、`agent/tools/`、`agent/services/` | 分别负责通用执行协议、基础设施适配、显式工具入口、业务查询/操作/展示。业务选择只发生在模型；工具不调用其他工具编排流程 |
| `product/`、`agent/composition.py`、`cli.py` | HTTP/页面/CLI 与依赖装配。可以同时装配两个板块，不能供业务模块反向调用 |
| `buy_points/`、新增 `buy_points/models.py` | 保留现有买分采集/查询扩展及其两张表，归 Workflow；没有证据表明功能已废弃，不为核心匹配重建擅自删除 |

根 `models.py` 和 `workspace_models.py` 在导入者迁出后删除，不留下转发导出兼容壳。会话/turn/message 模型归 `agent/adapters/`；正式知识模型仍归 `knowledge/`。目录拆分只用于消除明确的所有权混合，不按每个类创建新服务层。既有表格、费用、规范化、时间和遍历算法按审计逐导出保留，不能整包删除 `facts/` 或 `knowledge/transport.py`。

### B. 最终表集合与读写所有权

目标为 **46 张表（包括 `alembic_version`）**：原 57 张中退出 13 张，新增 2 张。表数是本次清单核对结果，不是质量指标；不以减少表数牺牲关联约束。

| 所有权 | 最终物理表（本行全部保留或按下文改造） |
|---|---|
| 基础设施 | `alembic_version` |
| Workflow 来源 | `sources`、`source_items`、`document_versions`、`collection_runs`、`document_sections`、`evidence_references`、`statusmatch_watches`、`statusmatch_watch_pages` |
| Workflow 处理 | `job_runs`、`analysis_runs`、`automation_leases`、`automation_runs`、`source_automation_states`、`initialization_runs`、新增 `activity_source_bindings`、`review_decisions`、`activity_edition_reviews` |
| Workflow 写、共享查询读 | `membership_programs`、`membership_tiers`、`membership_aliases`、`activities`、`activity_knowledge_versions`、`application_options`、`application_option_versions`、`option_mappings`、`option_prices`、`option_price_mappings`、`activity_documents`、`activity_briefs`、`activity_observation_state` |
| 用户数据服务 | `status_holdings`、`agent_wait_goals`、`user_business_operations`、`agent_operation_receipts` |
| Agent 持久化适配器 | `agent_interactions`、`agent_turns`、`agent_workspace_messages`、`agent_delivery_runs`、`agent_delivery_events`、`agent_run_checkpoints`、`agent_artifacts`、`agent_tool_calls`、新增 `agent_model_attempts` |
| Workflow 买分扩展 | `buy_points_snapshots`、`buy_points_offers` |

Agent 知识查询通过只读事务访问已发布数据，不能获得 Workflow 写服务。证据展示只能展开允许访问的来源正文，不把来源表当作正式知识接口。用户写服务与会话存储不共享一个可任意写所有域的业务接口；迁移和受控维护是显式基础设施操作。

退出表与替代职责：

| 退出表 | 目标职责承接方 |
|---|---|
| `status_events`、`event_revisions`、`fact_sets` | `activities`、统一草稿/正式版本、处理记录 |
| `event_evidence` | `activity_documents`、`document_sections`、`evidence_references` |
| `briefs`、`article_briefs` | `activity_briefs` |
| `article_analyses` | `analysis_runs` 的分类/拆分阶段结果；不重复保存同一次分析 |
| `article_opportunities`、`statusmatch_article_routes` | 发现契约、`activity_source_bindings`、草稿版本及其来源范围 |
| `statusmatch_article_supplements` | 第三方文档/证据进入同一草稿；不另存简报补丁 |
| `statusmatch_change_sets` | 相邻正式版本的确定性差异与 UPDATE 简报 |
| `knowledge_migration_links` | 正常来源绑定、期次审核及明确合并记录，不再保存旧表身份映射 |
| `gold_cases` | 仓库中的离线回归 fixture；不属于正常服务数据库 |

### C. 字段、约束与索引变更

新增表均使用 UUID 主键 `id`，`created_at/updated_at` 使用带时区时间；哈希为 SHA-256（64 字符），结构化载荷在 PostgreSQL 使用 JSONB。下文的“可空”以外新增字段均非空；通用字段遵循现有 Base 约定。

**C1 · `activity_source_bindings`（来源主体身份，不是第二套事实）**

- 字段：`source_item_id UUID → source_items.id`、`subject_key TEXT`、`activity_id UUID? → activities.id`、`status VARCHAR(30)`、`reason TEXT?`、`revision INTEGER default 0`。
- 唯一键 `(source_item_id, subject_key)`；索引 `(activity_id)`、`(status, updated_at)`；检查 `revision >= 0`，status 为 `UNRESOLVED/BOUND/RETIRED`，BOUND 必须有 activity_id。其他状态可保留之前的目标，但不得据此自动发布。
- 主来源 URL/邮件身份和来源内部活动主体建立联系；多个来源可以指向同一活动。subject_key 使用已验证项目标识或明确分配并持久化的主体键，不能使用提取列表下标、年份猜测或旧表 ID。
- 一篇文章多个活动各自有 binding；跨文档版本的拆分结果若不能可靠对齐已有主体，记 UNRESOLVED，保留原文和待审查原因，不按名称强行合并。FAQ/条款通过文档范围挂到同一主体，不因存在三页就造三个活动。
- 活动 identity_key 由首次已确认来源主体和明确期次建立，随后保持稳定；后续文章关联、来源变更不重建活动 ID。binding 指向新期次必须留下下述期次审核；历史版本的来源绑定不随当前指针变化。

**C2 · 处理与审核记录**

- `analysis_runs` 删除 `event_id`，新增可空 `source_binding_id UUID → activity_source_bindings.id`、`activity_id UUID → activities.id`、`base_version_id UUID`、`usage JSONB?`。组合外键 `(base_version_id, activity_id) → activity_knowledge_versions(id, activity_id)`，检查 base 非空时 activity 非空；新增索引 `(source_binding_id, stage, created_at)`、`(status, created_at)`。已有唯一 idempotency_key 保留。
- `analysis_runs.result` 按阶段使用严格 DTO：发现/筛选存分类与主体范围计划；提取/校验存版本引用、错误和统计，不再持久化一份可独立消费的 facts。模型/纯解析阶段都保留 provenance；纯计算明确 provider/model 为 deterministic，不伪造模型调用。完整原始模型载荷仅在受控调试记录中按需保存。
- `activity_knowledge_versions` 新增非空 `analysis_run_id UUID → analysis_runs.id` 且唯一、`source_binding_id UUID → activity_source_bindings.id`；索引 `(source_binding_id, created_at)`。每次提取以单个活动为单位；原始发现可拆出多个提取任务。binding/activity 一致性在锁定 binding 的发布事务中校验，避免用可变 binding 指针的组合外键破坏历史版本。
- `statusmatch_watches` 删除 `current_event_id`，新增可空 `source_binding_id UUID → activity_source_bindings.id`、唯一约束；监控可先创建，发现完成后再绑定。watch 不另存第二个活动当前指针。
- `activity_edition_reviews` 删除 `source_table/source_id`，替换为非空 `source_binding_id UUID → activity_source_bindings.id`；原来源索引替换为 `(source_binding_id, created_at)`。保留 base/target 活动、SAME/NEW/UNRESOLVED、reason 和 request_json；request_json 是来源版本、证据、预期 revision 的严格快照。只有当前来源范围支持的决定才能改 binding；来源不足时不推断新一期。
- `review_decisions` 保留 id/action/actor/reason/payload/时间；删除 `entity_type/entity_id/target_entity_id` 多态旧 ID，改为 `activity_id UUID → activities.id`、`knowledge_version_id UUID?`、`target_activity_id UUID? → activities.id`、`source_binding_id UUID? → activity_source_bindings.id`。版本与 activity 有组合外键；索引 `(activity_id, created_at)`、`(knowledge_version_id)`。action 限 `APPROVE/REJECT/MERGE`，reason 非空；MERGE 要求不同的 target 且版本为空，另外两者必须引用同一活动草稿版本且 target 为空。payload 保存当前契约的差异/证据/预期 revision，不存可执行旧格式补丁。修改草稿产生新草稿并重新校验；批准不能跳过证据/发布门槛。合并保留旧活动/历史引用，以 merged_into_id 和审核记录解释，不重写已发布版本。
- `job_runs` 保留调度/重试职责，result 仅记录处理记录/草稿/发布版本引用及失败，不复制事实。`initialization_runs` 的范围与完成结果使用本次清单和逐来源发布状态，不再嵌入固定历史窗口。其他自动化表沿用基线字段，退出旧 event/fact/brief ID 的 JSON 语义。

**C3 · 草稿、正式版本与派生产物**

- 复用 `activity_knowledge_versions` 的 DRAFT/VALIDATED/PUBLISHED/REJECTED 以及同一组方案、映射、费用、文档子表保存草稿；不新建另一套 draft-facts 表。草稿和正式版通过状态隔离；公开读取即使传入确切 ID 也必须检查 PUBLISHED。
- PUBLISHED 内容不可修改；修正产生新版本。保留当前版本/基础版本属于同一活动、费用属于同一方案映射、等级属于同一项目的现有组合外键和检查。所有 source/condition/evidence JSON 使用当前严格契约校验，不加旧版本解析分支。
- `activity_briefs` 新增非空 `activity_id UUID → activities.id`，版本及 previous_version 各自与 activity 建立组合外键；唯一键替换为 `(knowledge_version_id, brief_kind)`。kind 限 CURRENT/UPDATE，status 默认 READY 并检查只允许 READY，删除 error_code；失败发生在准备阶段，由 analysis/observation 记录，不能插入占位简报再宣布可用。generator_version 保留为出处，不允许同一发布版本重新生成不同可见简报。
- CURRENT 每版必需；语义变化且存在前版时必须有 UPDATE，previous_version 必须等于 base_version。跨行产物门槛由唯一 PublicationService 的短事务保证，不能误称普通 CHECK 能验证子表。故障注入与并发发布测试验证原子性。
- 完整图直接使用已发布 option/mapping/price 及共享算法，不新增持久 graph 真值表。查询在一致性快照内捕获实际版本集合；响应携带 snapshot_ref。需要跨请求继续分页时使用已保存的不可变查询结果/版本集合，不能换成最新数据仍沿用旧游标。

**C4 · 用户与会话字段**

- `status_holdings` 保留现有名称、规范 ID、identity_status、source_record、revision 和组合外键。未知项目允许“已授权但尚未解析”的真实记录，可空 ID 不再用于旧数据回填。补充 CHECK：tier 非空则 program 非空，已解析状态必须有完整规范 ID，revision >= 1。source_record 保留用户原话及操作来源，模型笔记不能充当授权证据。
- `agent_wait_goals` 删除旧消费专用 `preferences/research_statusmatcher/holding_node_ids`；条件和过滤只保存在当前 query，真实会籍基线在 holding_snapshot。保留其他基线字段；conditions_schema_version 只接受当前契约，清除 LEGACY_READ_ONLY 及旧结果适配。沿用单个活跃等待任务约束，不借此次重建引入多用户账户体系。
- `agent_interactions` 删除 `last_response`；state 仅容纳带 schema 的笔记引用/revision、焦点、展示引用及当前运行需要的会话状态，去 `import_source` 与旧 pending_action/reference 导入。其余实际 harness 使用字段保留，模型配置/协议版本不是应删除的历史残留。
- `agent_turns` 加唯一 `(id, workspace_id)`；`agent_workspace_messages`、`agent_tool_calls`、`agent_run_checkpoints` 的 `(turn_id, workspace_id)` 加组合外键；消息 role/ordinal 保持当前协议校验。`agent_interactions.active_turn_id` 加同会话组合外键，循环依赖采用可延迟约束。
- `agent_delivery_runs` 新增非空 `turn_id UUID`、同会话组合外键和唯一 turn_id；新增非空 `runtime_fingerprint JSONB`。checkpoint 与 delivery run 的 workspace/turn 也以组合唯一键/外键一致关联。artifact 的非空 created_by_turn_id 同样必须属于其 workspace；tool result artifact 必须属于调用会话（补相应组合唯一键/外键）。
- `agent_operation_receipts` 和 `user_business_operations` 保留当前字段；回执寿命可长于会话，实体删除后的 before/after 和授权快照仍有用，不强加级联删除。只支持本次目标 payload，去旧日志翻译；同幂等键不同载荷冲突、业务写与回执提交的原子性必须保留。

**C5 · `agent_model_attempts`（同链路请求与恢复记录）**

- 字段：`run_id UUID → agent_delivery_runs.id`、`attempt_no INTEGER`、`adapter_kind VARCHAR(30)`、`status VARCHAR(30)`、`request_hash VARCHAR(64)`、`response_hash VARCHAR(64)?`、`request_artifact_id UUID?`、`response_artifact_id UUID?`、`wire_artifact_id UUID?`、`usage JSONB?`、`error JSONB?`、`started_at TIMESTAMPTZ?`、`completed_at TIMESTAMPTZ?`。三种 artifact FK → agent_artifacts.id，删除载荷时 SET NULL；会话归属在写入/读取服务中校验。其余通用字段按本节定义。
- 唯一 `(run_id, attempt_no)`，attempt_no >= 1；status 限 PENDING/RUNNING/COMPLETED/FAILED/CANCELLED；索引 `(status, created_at)`。该表归持久化适配器，不让通用 harness 导入 ORM。
- request 是上下文编排后的实际 ModelPort 请求；wire 是提供方编码结果，去鉴权头。二者分别标明语义与实际传输口径，不能拿未投影的 schema 估计冒充实际 wire。response 记录实际返回及可恢复工具调用，不能伪造已执行效果。
- 常态保留必要元数据/usage，完整请求与 wire 仅在限定验收会话开启。载荷复用 artifact TTL，不永久复制全部历史。usage 区分估算、提供方输入/输出/cache token，人工端无提供方 token，写 null 而非 0；每请求和整轮分别汇总。

### D. AIWorkflow 的单一生产契约与发布顺序

1. **发现**：采集得到 SourceItem/DocumentVersion；筛选与拆分产出 `DiscoveryResult(document_version_id, classification, subjects[])`。subject 含持久主体键/待确认状态、相关文档角色、精确 section 范围、身份依据。官方主页/FAQ/条款解析和文章拆分可以采用不同来源适配器，但共享该输出边界。未覆盖正文、拆分不清或身份冲突显式 DEFERRED，不能静默跳过。
2. **身份/来源计划**：`SourcePlan(binding_id, activity_id, expected_binding_revision, base_version_id, documents[{id, hash, role, section_scope}], catalog_scope, extraction_key)`。发现阶段只整理身份与范围，不先生成旧完整事实。目录可由有依据的名称/表格整理，提取只接相关目录及明确的解析缺口；不能把未知目录强行猜成已有项目。
3. **提取**：来源适配器的确定性表格/费用结果和模型提取共同产出当前 `KnowledgeDraft` 契约，校验后落同一草稿版本/关系表。extraction_key 包含 binding、来源范围哈希、base、目录相关版本及解析/提示/schema 配置；审核修正增加审核请求 ID/修正内容哈希，生成独立 analysis_run 和草稿，不覆盖已记录结果。重复任务复用或返回明确状态。模型和网络始终在数据库事务之外。
4. **准备**：校验身份、引用范围、证据逐字对应及实际语义、映射/收费适用关系；从同一已校验草稿视图生成 CURRENT/UPDATE 简报和图投影校验结果。现有确定性简报生成可复用，解除必须先读 PUBLISHED 的前提；不再追加一次“旧简报转新事实”模型调用。
5. **发布**：短事务锁定 activity/binding/草稿，重核 expected base、binding revision、来源计划和产物哈希；插入 READY 简报、置 PUBLISHED、最后切 current_version_id，一次提交。并发失败返回 CONFLICT 重算，不覆盖别人更新；任何准备/提交失败都保留上个完整正式版本，并可见失败状态。重复提交返回同一正式版本。
6. **增量**：正常 run-source/run-daily 与显式初始化都调用上述入口，以逐来源 published/reused/deferred/failed 状态结束。关闭活动也由有来源证据的同契约草稿发布；未知关闭/新期次不能靠年份或关键词直接改事实。来源未变化复用，来源变化重算，历史文档与版本引用保留。

### E. 正常入口、人工 ModelPort 与交付检查

- 正常运行入口仍是 `journeyplus product-api --host 127.0.0.1 --port 8023`，页面保留 `/workspace`、`/knowledge`、`/explore`。同进程装配允许，但知识 router 不能依赖 Agent 初始化成功；独立 knowledge-server/agent-server 是板块独立性入口，使用同一目标 schema，不另起一套事实系统。
- 生产入口保留采集、run-source/run-daily、automation-status、knowledge-refresh、review-edition 的必要能力；初始化合并为一个接收显式 manifest 的入口。旧 fact/backfill/shadow/promote/固定日期初始化及旧图/简报命令在替代完成后退出。买分入口独立保留。当前路由版本号无需为整洁全部改名；退出的是旧控制器和 DTO，不是字符串中所有 v2/v3。
- 新增 HumanModelPort 适配器和受控运维读写端：网页仍创建相同会话/turn/run；请求经同一个 ContextProjector 后排入 agent_model_attempts；人工只从实际 request 读取信息，提交相同 ModelResponse 文本/工具调用。正常 Registry 执行，结果回到同一下一轮请求。禁止脚本直接调业务工具、写入模拟结果或换评估库。
- 运维端使用本机受保护入口及显式启用配置，不放到普通模型工具中，不向外网无鉴权暴露。每次响应带 attempt ID、request hash；重复相同响应幂等，不同响应冲突，迟到/取消后的响应拒绝。等待人工与提供方超时分开配置，页面显示等待状态；取消/恢复仍走同一 checkpoint，不把人工思考时间伪装为模型用量。
- 第一视角人工决策前不得查 DB/旁路详情。第三视角在该次决策提交后关联 request→model response→tool call→artifact/receipt→SSE→页面，再查对应数据库记录/来源核实；审计额外数据不回填模型请求。两个视角覆盖同一个 run，不能拿另一次脚本运行拼证据。
- A7 的处理放在业务结果/展示契约：写入成功只能由实际 operation receipt 生成状态卡；结构化事实引用按字段类型生成可读说明，禁止直接 dump 任意 JSON；路径展示明确 returned/total、续读和未确定条件。harness 的 COMPLETED 只表示执行结束，页面另依据实际交付/回执展示状态。
- 通用 harness 不增加品牌关键词判断、固定工具顺序或另一个“纠错模型”。自由文本仍可能说错，不能用 typed delivery 声明证明其全部语义；保留校验声明与实际产物一致的检查，并在真实网页逐项验收“说保存却没保存”“说全部却未读完”。发现宣称与证据不一致应明确失败并修复，不以空 deliveries 通过代表正确。
- 模型可替换；配置分别命名 Workflow 与 Agent，取消 Workflow 非必要的 DeepSeek 型号钉死。启动、schema、知识覆盖、模型就绪独立显示；空库可展示空/未初始化状态，不能宣称知识就绪。加载时捕获源码/提示/工具/schema/模型配置摘要与启动时间，运行 status 与 run 固定该指纹；磁盘变化报告需重启，不能把 Git HEAD 当已加载代码证明。

### F. 上下文正确性与效率边界

- 原始用户消息是授权与纠正的依据；真实会籍、假设、工具事实和模型 note 有不同来源标签。history 工具是续读能力，不足以证明被省略约束已保留。当前任务相关原话/纠正必须可见；不能确定有效约束已覆盖时保留原文或明确请求续读，不先有损概括再期待模型猜回来。
- note 保存原话引用与版本，不能提升为已确认用户事实；不能自动执行 note 中的动作。被替代的纠正、未完成请求、实际写回执和未读页位置纳入上下文回归样例，不新增无法校验的长期语义真值表。
- 查询 DTO 保留版本、证据、未知/冲突、覆盖与 continuation；大结果通过可展开 artifact 传输，缩减视图明确遗漏范围。请求预算按真实适配器 wire 计算并与提供方 usage 对照，修正审计中 raw schema 与运行 schema 测试口径错位，不简单提高上限。
- 优化候选仅记录到任务 8：每请求复用一次 availability 快照；拆开 state/近期消息/历史分页，避免先全量加载再重复加载；按稳定引用复用重复结果；评估相关目录和工具定义开销。是否实施取决于同场景正确性和实际请求数据，不在尚未验收时先缩窄能力。

### G. 空库基线、退出顺序与实施门槛

1. **先落清理与验收清单**：完成 1.6、2.1–2.2，明确个人记录、来源 manifest、写入测试主体及一次性 GHA 对象。当前只是结构冻结，个人数据删除授权不能由表清单推断。
2. **备份、停写、清数据**：先验证备份可恢复，再停止已核实的全部写入者并取得最终一致备份/核对点；按批准范围清旧知识/项目临时资源。清理后服务保持维护状态，旧写链不恢复。备份只在外部恢复路径保留，不让正常启动读取它。
3. **存储与生产切换**：实现 B/C 的模型及空库基线，先解除 discovery→draft→publication 对旧表的依赖，再切 run-source/run-daily/初始化/review。此期间无需让旧 schema 跟新 schema 并行可用。
4. **消费与产品切换**：知识页/图/Agent 使用统一读取；接真实用户服务、harness、人工 ModelPort、状态与运行指纹。旧 v1 会籍等入口如承担有效用户功能，功能迁到共享服务后删除旧控制器；不能只禁用接口导致用户功能消失。
5. **删除旧实现**：在生产、查询、页面、CLI、review、调度、脚本、测试引用全部迁出后删除 B 的 13 表模型、旧消费控制器、rollout/legacy 开关、迁移/回填/导入代码。按审计的 17 脚本逐项处理：人工脚本接正常服务；shadow/promote/固定旧样本生产入口退出；纯算法与离线回归/恢复工具按真实用途保留。
6. **唯一 active Alembic 空库基线**：旧 0001–0028 不进入新库建表路径；从版本控制/限定恢复备份保留历史追溯，不在 active versions 目录建旧表再拆。新 revision 明确只支持空库和后续目标 schema 升级；检测到旧库/未知 revision 必须拒绝启动，不能自动清库或回退。实现中 PostgreSQL 是正常运行验收依据，SQLite 仅作允许的局部测试，不作为自动运行降级。
7. **重新生产与验收**：建立最终空库，AIWorkflow 从真实来源生成正式知识，然后走正常网页人工 ModelPort、同网页经济型真实模型、最后效果不退化的效率比较。文章准入移除固定 Sep 6 历史阈值；执行日 LL 与 GHA 规则只存在本次 manifest，不变成长期禁采。

本阶段设计检查：57 张现有表均有明确去向；删除表的声明外键消费者 `analysis_runs.event_id`、`statusmatch_watches.current_event_id` 均有替换；多态旧 ID/JSON 消费也必须按退出清单移除。后续每个核心模块必须完成对应边界/事务验证，再进入下一阶段，最后仍以真实网页证明系统可用。

## Risks / Trade-offs

- 清空及重建存在停服时间：按用户接受的无兼容路线执行，提前列出停写者与恢复步骤，不能重建途中悄悄恢复旧写链。
- 误删必要处理能力会阻断数据生产：每项删除必须有消费者与替代路径证据；不以文件年代判定。
- 人工决策可以验证契约，但不能证明第三方模型表现：分别记录人工和真实模型结果，真实模型失败仍需定位到同一链路。
- 真实网页写入验收可能污染个人资料：执行前明确可清理的测试主体/记录边界，不为测试额外搭建一套产品系统。
- 完整图和长历史存在规模成本：披露实际查询范围与资源限制，保留续读能力，不把截断伪装成全量。

## Migration Plan

本次采用清库重建，不提供旧数据迁移兼容。按 tasks.md 的阶段顺序推进：审计和最终结构设计；备份/停写/清理；代码与旧依赖退出；空库建表/重新生产；人工网页及真实模型验收；效率复验和交付。失败时按已验证备份和运行基线恢复明确的服务状态，不让半建成结构对外宣称就绪。

## Open Questions

结构、表去留、字段约束和退出顺序已在上文冻结。尚待任务 1.6/2.1/2.2 落实的是个人数据处置范围、初始化来源明细及 GHA 对象、正常网页写入验收主体与具体预期样例；它们不阻止设计，但未明确前不能执行依赖的删除/写入验收。新发现的实现事实若需要改变结构，须说明依据并同步本设计与任务，不保留暗中的第二套方案。
