## Context

当前普通文档由 `V1Workflow` 顺序执行 `StatusOpportunityPipeline`、`FactConsolidator` 和 `BriefGenerator`。其中全文分类同时输出活动提示；每个提示再经过候选召回和可选关系 AI；事件形成后，事实 AI 会重新读取该事件已关联的历史正文，最后简报 AI 读取 FactSet。常见单机会文章因此需要分类、关系、事实和简报三至四次模型调用，候选材料与历史正文还会被重复发送。

StatusMatch 官方项目已经有独立的 HOME + FAQ 项目工作流：确定性解析 FAQ 表格，一次项目事实提取，再对物质变化的 FactSet 生成一次简报。第三方文章也已经通过精确项目链接路由到独立补充工作流。该专用链路刚完成验收，本变更不得改变它的项目身份、FactSet、Brief、监控和默认官方图语义。

产品当前只需要让 LoyaltyLobby 进入通用文章处理；StatusMatch/GetStatus 邮件仍然只负责专用项目发现。单一通用来源下没有跨来源事件归并价值，因此继续维护逐文章候选召回、关系 AI 和跨材料事实协调不符合当前成本收益。

目标结构为：

```text
status_services_mail ───────────────▶ 现有 StatusMatch 项目链路（不变）

loyaltylobby_feed
        │
        ▼
  组合入口确定性路由
        │
        ├─ 精确 *.statusmatch.com ─▶ 第三方补充（一次 AI）
        │
        └─ 普通文章 ─▶ 批量标题筛选
                              │
                    PASS / NEEDS_BODY
                              │
                              ▼
                   一次正文结构化理解
                              │
                              ▼
              独立 ArticleOpportunity + FactSnapshot
                              │
                              ▼
                     物质变化时生成简报
```

## Goals / Non-Goals

**Goals:**

- 通用公开来源暂时只开放 LoyaltyLobby，邮件与 StatusMatch 专用链路保持隔离。
- 用批量标题筛选避免对明显无关文章发送全文，且以高召回和失败放行为首要约束。
- 每篇普通文章只读取一次正文，同时完成最终分类、文档内机会拆分、事实和证据提取。
- 把每个文章机会作为独立、不可变、可审计的来源记录，不进行任何跨文章关联或事实合并。
- 保留事实之后的独立简报调用，并在事实未变化时复用。
- 让第三方 StatusMatch 文章在现有一次补充调用中额外产生候选匹配声明，保持官方事实和第三方来源隔离。
- 通过稳定 opportunity ID、来源、身份字段、窗口、链接、事实和证据为以后独立的记录关联系统保留输入，不预先实现关联框架。
- 采用旁路 V2、影子验证和配置切换，避免直接重写已运行的 V1 或 StatusMatch 专用链路。

**Non-Goals:**

- 不实现候选事件召回、pairwise 关系判断、相似度模型、embedding、向量数据库、聚类或人工合并工作流。
- 不创建空的 `AssociationResolver`、候选列表、`group_id` 或当前无消费者的关联表。
- 不把同一来源的两篇文章自动视为同一事件或更新关系；即使它们描述同一现实活动也保持独立。
- 不将普通文章机会写入共享 `StatusEvent` 后再模拟“一事件一文章”。
- 不恢复其他公开来源的自动调度，不删除其适配器、原文或历史结果。
- 不合并正文理解与简报为一次调用，也不让简报读取原文。
- 不修改 StatusMatch 官方 HOME + FAQ 的提取次数、FactSet Schema、Brief 或当前主图输入。
- 不引入新的外部基础设施或常驻调度服务。

## Decisions

### 1. 用旁路 Article Pipeline V2 替代 LoyaltyLobby 的 V1 调用

新增独立的文章级包，而不是继续修改 `V1Workflow`：

```text
article_pipeline/
├── contracts.py       # 标题筛选、ArticleAnalysis、ArticleOpportunity
├── screening.py       # 批量标题筛选
├── interpretation.py  # 一次正文结构化提取和证据校验
├── facts.py           # 单文档事实规范化与签名
├── briefs.py          # 文章机会简报的幂等适配
└── workflow.py        # 只编排文章级阶段

membership/
├── contracts.py       # 中立 MembershipMapping/Claim/Provenance
└── reconciliation.py  # 候选关系与官方映射的确定性比较
```

自动编排层是组合入口，同时依赖 V2 与 StatusMatch 专用 Handler；`article_pipeline` 不导入 `journeyplus.statusmatch`，StatusMatch 也不导入文章 V2。路由先于两个 Handler 执行，普通文档和专用文档互斥。

替代方案是在 `operations.py`、`StatusOpportunityPipeline` 和 `FactConsolidator` 中继续增加 LoyaltyLobby 条件。这会保留当前通用层对 StatusMatch watch、表格解析和文章路由的反向依赖，也难以证明关系 AI 已彻底退出，因此不采用。

### 2. 来源收缩通过处理策略实现，保留原始来源资产

运行配置明确区分：

```text
generic_source_ids = {loyaltylobby_feed}
special_source_ids = {status_services_mail}
```

其他公开来源关闭自动调度和 V2 选择，但注册表、适配器、SourceItem、DocumentVersion 及历史派生数据保留。这样来源收缩可回滚，也不会把产品范围变化错误实现为破坏性数据删除。

StatusMatch watch 的独立页面监控仍按现有方式运行；它不是通用公开文章来源。

### 3. 精确 StatusMatch 项目链接在标题筛选之前路由

LoyaltyLobby Feed 已包含可处理正文，编排层可以在不调用模型的情况下检查受支持项目链接。命中后直接使用现有第三方 route/project preparation/article workflow，不再浪费标题筛选，也避免同一文档同时生成通用文章机会和 StatusMatch supplement。

只有精确项目专属 host 触发专用路由；模糊提及 “StatusMatch”、普通 `www.statusmatch.com` 或无可归属项目的链接不触发绑定。

### 4. 标题筛选是批量高召回漏斗，不是最终分类

标题请求只包含稳定文档 ID 和 SourceItem.title，不包含摘要或正文。输出使用：

```text
PASS        标题明显可能属于会籍机会
DROP        标题高置信度明确无关
NEEDS_BODY  标题本身无法可靠判断
```

批次容量由配置控制，初始默认值可取 25，并同时受模型输入上限约束。持久化仍按文档逐项记录，以规范化标题哈希、提示词、Schema 和模型配置作为幂等版本。批次调用部分失败、缺项、重复 ID 或整体失败时，受影响文档全部降级为 `NEEDS_BODY`。

不把 `DROP` 当成普通三分类结果：它只有在置信度达到配置阈值、输出完整且影子阶段门通过时才有阻断权。该设计允许标题明显含有 “benefits” 或 “guide” 但正文仍可能包含具体活动的材料进入 `NEEDS_BODY`，降低标题假阴性。

替代方案是一篇标题一次调用。它仍然让调用数与文章数线性增长，没有利用标题输入极短的特点，因此不采用。纯关键词规则可作为请求前的确定性快速路径或校验，但不能独立承担最终丢弃权。

### 5. 正文模型输出文章级完整快照而不是 EventHint

定义新的结构化契约：

```text
ArticleInterpretation
├── label
├── confidence
├── reason
└── opportunities[]
    ├── local_index
    ├── program
    ├── target_status
    ├── summary
    ├── application_start / application_deadline
    ├── action_links[]
    ├── facts
    ├── application_routes[]
    ├── membership_mapping_claims[]
    └── evidence aliases / exact quotes
```

一次调用必须同时完成现有最终标签边界、文档内现实机会拆分和单文档事实提取。`NONE` 不含 opportunities；`STATUS_OPPORTUNITY` 至少包含一个；`UNCERTAIN` 保留分析但不发布简报。

模型只输出证据别名、短 locator 和逐字 quote。服务层使用当前 DocumentVersion 注入 UUID 与 canonical URL，并验证 quote 存在、行动链接属于当前正文、日期和字段没有跨 opportunity 串线。模型不得生成数据库 ID。

这取代现有“全文分类 → EventHint → 再把全文送给 FactConsolidator”的两次正文理解。纠错重试只针对 Schema、引用归属和确定性校验失败，并保持有界。

### 6. ArticleOpportunity 是当前最终业务记录，不建立共享事件

新增文章级持久化，而不是复用 `StatusEvent`：

```text
ArticleAnalysisRecord
├── id
├── document_version_id
├── source_item_id
├── analysis_run_id
├── input_version
├── label / confidence / reason / status
└── content_signature

ArticleOpportunityRecord
├── id
├── article_analysis_id
├── opportunity_index
├── program / target_status / summary
├── application_start / application_deadline
├── action_links JSON
├── facts JSON
├── fact_signature
├── lifecycle_status
├── current_brief_id
└── status
```

DocumentVersion 的成功分析不可变；SourceItem 的默认读取选择最新成功 DocumentVersion 对应的分析。相同 DocumentVersion 与分析版本重跑复用现有结果。新 DocumentVersion 创建新分析和新机会记录，旧版本保留。

即使两篇文章的项目、链接和窗口完全相同，也不读取彼此、不共享 opportunity ID、不建立候选、不修改对方事实。这样当前系统真实表达“文章报道了什么”，而不是提前表达“现实世界里这些报道是否同一事件”。

未来关联只需新增独立投影：

```text
ArticleOpportunityRecord[]
          │
          ▼
future association job
          │
          ▼
OpportunityGroup + GroupMember
```

未来 join 表引用稳定 opportunity ID；当前表无需预留 `group_id`、关系字段或候选 JSON。文章记录已有 program、target status、时间、action links、canonical URL、发布时间、事实、证据和签名，足以支持以后调研并接入常见的 blocking → pairwise scoring → clustering/人工复核架构。

### 7. 单文档事实快照不再执行 AI consolidation

文章机会 facts 复用现有 `FactField`、`ApplicationRoute`、映射核心等通用字段约束，但使用不要求 `event_id` 的文章事实快照容器。服务层只做：

1. 证据别名解析和逐字引用校验；
2. URL、项目文字和北京时间日期规范化；
3. 未知字段守卫和结构冲突校验；
4. 事实物质签名；
5. 基于有证据窗口的生命周期计算。

它不读取其他文章、不复用 `EventEvidence`、不调用 `FactConsolidator._reconcile`，也不产生 `SAME_EVENT / UPDATE_OF` 语义。单篇文章内部若存在两条合法申请路径，模型输出 `application_routes`；同文真实互斥信息可在该机会快照中标记 conflict，但不尝试跨来源裁决。

### 8. 文章简报使用独立持久化适配并复用输出契约

StatusMatch 官方 `BriefGenerator` 当前以 `FactSetRecord.event_id` 和 `BriefRecord` 为中心。为避免修改已调好的专用行为，V2 使用文章机会简报适配：

```text
ArticleBriefRecord
├── id
├── article_opportunity_id
├── analysis_run_id
├── fact_signature / input_version
├── version
└── content JSON（复用 Brief 输出契约）
```

文章简报复用中文编辑规则、已知/未知字段守卫、来源白名单和 grounding 校验的通用实现，但拥有文章机会自己的幂等键和持久化记录。它只读取该 opportunity 的 facts，不读取正文。

如果事实签名不变且简报提示词、Schema、模型配置未变，复用已有简报。简报失败不会回滚成功的文章分析和事实；独立任务可重试。一个多机会文章只有一次正文调用，但每个需要发布的机会各有一次隔离简报调用，以换取局部失败隔离和稳定幂等。

### 9. 模型调用预算作为运行时不变量

不计有限校验重试时：

| 场景 | 调用预算 |
|---|---:|
| 一个标题批次 | 1 |
| 有效高置信度 DROP | 仅摊销标题批次，无正文调用 |
| 单机会普通正例 | 正文 1 + 简报 1 |
| K 个机会的普通正例 | 正文 1 + 简报 K |
| StatusMatch 第三方文章 | 现有补充 1 |
| 相同版本完整重跑 | 0 |
| 通用关系/事实协调 | 0 |

新增 `TITLE_SCREENING` 和 `ARTICLE_INTERPRETATION` 分析阶段；文章简报使用可区分的文章简报阶段或 subject 类型。自动运行计数器必须分别报告标题批次调用、正文调用、文章简报调用和 StatusMatch 专用调用，避免只看总数无法发现回归。

### 10. 第三方候选映射共享核心结构但不共享权威容器

中立领域层定义：

```text
MembershipMapping
├── source_program
├── source_tiers[]
├── target_tier
├── availability
├── conditions
├── evidence[]
├── conflict
└── conflict_note

MembershipMappingClaim
├── mapping
├── target_program（由绑定 event 物化）
├── provenance
│   ├── source_type
│   ├── source_document_version_id
│   ├── source_url
│   ├── route_id
│   └── project_host
├── compared_fact_set_id
└── verification_status
```

StatusMatch 官方 FactSet 继续保存现有 `StatusMapping`。第三方 supplement 增加独立 `mapping_claims` JSON 或规范化子记录；无论采用哪种持久化，都不能把 claim 追加到官方 FactSet。

第三方文章现有一次 AI 输入已经包含 ARTICLE、官方 FactSet 覆盖和官方 Brief，因此同一次输出增加 `candidate_status_mappings`，不增加模型阶段。只允许正文逐字支持的直接映射，不把 `A → B` 与 `B → C` 推导为 `A → C`。

确定性对照产生：

- `CORROBORATED`：与当前官方映射等价，只补充来源，不新增拓扑；
- `CANDIDATE`：官方当前不存在，默认只进入可选候选层；
- `CONFLICTING`：与官方互斥，保存双方来源且不可遍历；
- `REJECTED`：非直接、缺字段或证据无效；
- `APPROVED`：显式人工确认后的候选，可由图策略选择为第三方可遍历 claim。

默认 `MembershipGraphService.build()` 的官方视图保持只读取 ACTIVE watch 当前 FactSet。候选/冲突层使用显式查询入口；批准关系即使进入可遍历图也保留第三方 provenance，仍不修改官方 FactSet。

### 11. 版本与幂等边界按阶段独立

建议键空间：

```text
title-screen:{document_id}:{title_hash}:{model_config}:{prompt}:{schema}
article-interpretation:{document_id}:{normalized_hash}:{model_config}:{prompt}:{schema}
article-brief:{opportunity_id}:{fact_signature}:{model_config}:{prompt}:{schema}
statusmatch-article:{route_id}:{article/fact/brief/model/prompt/schema input version}
```

标题批次一次调用对应多份逐文档结果；批次协调器可以记录 invocation ID 供成本审计，但逐文档结果决定幂等和续跑。正文或简报提示词升级只重跑对应阶段，不应让无关阶段隐式失效。当前 V1 的整条 workflow fingerprint 不用于 V2，因为任何阶段版本变化都让整篇文章从头运行会抵消拆分后的复用收益。

### 12. 影子验证先于切换，旧 V1 延后清理

标题筛选先在冻结金标和 LoyaltyLobby 历史材料上影子运行，不阻断正文。阶段门要求所有已知正例为 `PASS` 或 `NEEDS_BODY`。随后 V2 对同一批 LoyaltyLobby 文档与 V1 比较最终标签、文档内机会数量、关键事实、证据、简报和调用统计。

切换通过显式处理策略完成；旧 V1、旧历史事件和分析运行先保留只读以便回滚和对照。只有 V2 经过真实初始化批次及短期自动运行观察后，才另立清理任务删除无调用方代码。本变更不通过迁移删除旧事件。

## Risks / Trade-offs

- [标题可能隐藏正文中的正例] → 标题筛选只做高召回漏斗，低置信度和失败一律读正文；先用冻结金标和真实 LoyaltyLobby 影子验证，已知正例零有效 DROP 才启用阻断。
- [一次正文调用同时分类和提取事实，Schema 更大] → 使用有界机会数量、证据别名、严格结构校验和最多有限纠错重试；影子比较机会串线、字段缺失和无依据事实。
- [不做跨文章关联会显示重复现实活动] → 当前只有一个通用来源，明确接受文章级重复；原始 opportunity 不可变，未来可通过独立分组投影解决而无需重跑正文。
- [同一 SourceItem 新版本产生新的 opportunity ID] → 默认读取只显示最新成功分析，旧版本保留审计；未来关联以需要展示的当前 opportunity 为输入。
- [新增文章级存储和简报记录与旧事件 API 并存] → 通过 V2 专用查询/视图逐步接入，V1 保持回滚；不强行把文章记录伪装成共享事件。
- [通用事实模型与 StatusMatch FactSet 出现字段漂移] → 复用 `FactField`、`ApplicationRoute`、Brief 和 MembershipMapping 等领域组件，只让顶层快照标识与持久化容器分离。
- [第三方候选关系被误当官方事实] → 独立 provenance、verification status、持久化容器和显式候选图入口；默认官方图输入不变。
- [一个多机会文章仍需多次简报调用] → 保留每机会失败隔离与幂等；正文只调用一次，后续事实不变时简报复用。观察实际多机会比例后再决定是否另立批量简报变更。
- [关闭其他来源自动采集降低覆盖面] → 这是当前明确产品范围；保留适配器和历史原文，未来按来源重新验收后再开启。

## Migration Plan

1. 增加文章 V2 契约、文章分析/机会/简报持久化模型及数据库迁移，不改变当前路由。
2. 增加批量标题筛选、逐文档幂等结果和调用统计，先以影子模式运行；用冻结金标及 LoyaltyLobby 历史样本验证正例不被有效 DROP。
3. 实现一次正文结构化理解、单文档事实规范化、证据校验、生命周期和文章简报适配；增加单机会、多机会、NONE、UNCERTAIN、失败隔离和零调用重跑测试。
4. 让自动编排组合入口执行精确 StatusMatch 路由，并把未命中的 LoyaltyLobby 文档影子送入 V2；确认同一文档不会同时进入两条业务链路。
5. 使用相同 LoyaltyLobby 文章集比较 V1 与 V2 的分类、机会数、事实、证据、简报、调用次数和输入规模；阻塞差异解决前不切换。
6. 扩展第三方 StatusMatch 补充契约和持久化，增加候选映射的引用校验、官方对照、状态迁移及默认图隔离测试；验证补充仍为一次模型阶段。
7. 将通用处理策略切换为只选择 LoyaltyLobby V2，关闭其他公开来源自动调度；`status_services_mail` 和 StatusMatch watch 维持专用处理。
8. 运行受控真实 LoyaltyLobby 初始化和短期自动观察，确认没有重复处理、无正文标题筛除、无证据事实、跨机会串线、额外关系/事实模型调用或 StatusMatch 行为回归。
9. 验收后把旧 V1 保留为禁用回滚路径；删除死代码和旧通用事件链路另立后续清理变更，避免与本次行为切换混在一起。

回滚时只需把 LoyaltyLobby 处理策略切回 V1 并关闭标题阻断和 V2 任务。V2 新表与历史结果保留，不做破坏性回滚；其他来源保持关闭，StatusMatch 专用链路不受切换影响。

## Open Questions

- 标题批次容量和高置信度 DROP 阈值在影子运行报告中确定；实现必须配置化，不写死为产品语义。
- 文章级 V2 查询是否立即替换当前事件查询入口，还是先提供并行只读接口，由实现前的 API/UI 影响检查决定；无论选择哪种方式，都不得把文章机会重新引入跨文章关系流程。
- `APPROVED` 第三方匹配关系的人工操作入口可以复用现有复核服务或新增窄接口；在入口确定前，系统仍可完成候选提取、对照和只读展示，但不得自动批准。
