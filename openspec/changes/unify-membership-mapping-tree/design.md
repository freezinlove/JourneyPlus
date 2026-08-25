## Context

当前实现已经有两条相互隔离的处理链：

- StatusMatch HOME+FAQ 生成官方 FactSet、官方 Brief 和官方会员图；其 watch/event 负责活动关闭与归档。
- 普通第三方文章生成按 DocumentVersion 保存的 ArticleAnalysis、ArticleOpportunity、文章 FactSet 和 Brief；正文一次结构化理解已经可以提取 `status_mappings`。

在上一轮实验实现中，精确链接 `*.statusmatch.com` 的第三方文章还会在 highlights 调用中提取 `candidate_status_mappings`，保存到 `mapping_claims`，并提供候选/批准图层。这混淆了两类不同用途：这种文章本来是官方项目的补充阅读，不应成为另一套匹配事实来源；真正需要进入统一用户树的是未绑定 StatusMatch 项目的普通文章机会。

本变更跨越文章模型、生命周期、图投影、CLI/API 和自动化，但约束是：不修改 StatusMatch 官方事实生产逻辑、不新增 AI 阶段、不做跨文章关联，并保证历史数据可审计。

## Goals / Non-Goals

**Goals:**

- 让 StatusMatch 官方直接映射与当前有效的普通第三方直接映射在同一棵用户树中以相同视觉语义展示。
- 通过独立读取投影实现低耦合；任一来源链路都不直接调用另一条来源工作流。
- 对普通第三方映射实施“明确截止优先，否则固定 180 天”的确定性生命周期。
- 支持混合来源的递归多跳、确定性同边去重、循环/交叉引用/深度/节点/分支限制。
- 内部完整保留来源、证据、贡献者和归档信息，同时避免默认用户合同暴露来源等级差异。
- 保持现有 StatusMatch FactSet、Brief、生命周期和官方审计图的行为与模型调用预算不变。

**Non-Goals:**

- 不做跨文章事件合并、同消息聚类、候选召回、关系 AI 或事实协调。
- 不把多跳可达结果写成新的直接映射，也不把统一树结果回写到任一 FactSet。
- 不让 StatusMatch 关联文章修改官方 FactSet、Brief、watch/event 或图边。
- 不引入第三方关系审核/批准图层；文章自身冲突或无效的映射不进入用户树。
- 本次只启用已有 LoyaltyLobby 普通文章适配器，但领域接口不得写死 LoyaltyLobby。

## Decisions

### 1. 固定三类材料的权威边界

| 材料 | 产物 | 是否贡献用户树 | 生命周期 |
| --- | --- | --- | --- |
| StatusMatch HOME+FAQ | 官方 FactSet、Brief、直接映射 | 是 | 现有 ACTIVE watch/event |
| 精确链接 StatusMatch 项目的第三方文章 | 项目补充 highlights | 否 | 跟随项目补充读取与历史，不存在映射有效期 |
| 未路由到 StatusMatch 的普通第三方文章 | ArticleOpportunity、FactSet、Brief、直接映射 | 是 | 明确截止或默认 180 天 |

StatusMatch 路由的确定性谓词继续作为两条文章分支的唯一分流条件。普通文章贡献适配器还会做防御性排除：只要其 DocumentVersion 存在 StatusMatchArticleRoute，就不得从普通适配器产生贡献。

选择这一边界而不是让所有第三方内容都进入候选图层，是因为“项目补充”与“独立活动来源”的生命周期和权威关系不同；统一它们只会把 StatusMatch 工作流与通用文章发布策略重新耦合。

### 2. 新建来源中立的读取投影，不改写官方图

新增 `MembershipMappingContribution` 内部契约，最少包含：稳定贡献 ID、目标项目、现有 `StatusMapping`、来源种类、原始主体 ID、证据、可见区间和归档状态。两个只读适配器分别提供贡献：

- `StatusMatchOfficialContributionAdapter` 只读取 ACTIVE watch 当前 event 的当前 FactSet。
- `OrdinaryArticleContributionAdapter` 只读取每个 SourceItem 最新成功 ArticleAnalysis 下、当前可见且证据有效的 ArticleOpportunity FactSet。

新增 `UnifiedMembershipTreeService` 聚合这两个适配器。现有 `MembershipGraphService` 继续只读取官方 FactSet，用于官方图审计和回归，不依赖文章模型。面向用户的树 CLI/API 改用统一服务；管理员审计可以查看统一贡献明细。

选择新读取服务而不是直接扩展 StatusMatch 图查询，是为了保持依赖方向为“读取层依赖两个来源适配器”，避免 StatusMatch 官方服务依赖通用文章数据库状态。规范化、别名解析和有界遍历算法应从现有图实现中提取为来源无关组件供两者复用，而不是复制两份算法。

### 3. 直接边规范化、去重与展示

每个 AVAILABLE 或 CONDITIONAL 映射按 `source_program + source_tier → target_program + target_tier` 展开为直接贡献。节点和别名继续复用现有规范化规则。UNAVAILABLE 映射只进入审计；普通文章中 `conflict=true`、证据无效或分析非成功的映射不进入默认用户树。

边身份只由规范化后的起点节点和终点节点决定。同一边的多个有效贡献聚合为一条用户边，并在内部保留全部 contributor ID、证据、条件和有效期。不同条件以来源无关的条件变体去重保存；默认用户合同可呈现条件/不确定性，但不返回 `source_type`、官方徽标、文章徽标或贡献者列表。管理/审计合同单独返回这些溯源字段。

选择读取时聚合而不是持久化一张“最终边表”，可以避免失效、恢复、官方归档或新文档版本到来时做跨来源同步，也不会产生事实合并含义。

### 4. 多跳只遍历直接边

统一服务以聚合后的当前直接边建立邻接表。A→B 与 B→C 可以分别来自任一适配器，因此用户树可以得到 A→B→C；服务不得生成、保存或标注一个不存在原始贡献的 A→C 边。

沿用现有分支祖先检测、全查询已展开节点检测、`max_depth`、`max_nodes` 和 `max_branches`：回到祖先时返回 CYCLE 叶子，重复展开节点时返回 CROSS_REFERENCE，达到限制时报告具体截断原因。这样既支持树继续延伸，也不会因来源混合产生无限递归。

### 5. 普通文章映射的 180 天是内部可见期，不是业务截止日

为 `ArticleOpportunityRecord` 增加：

- `visibility_until_at`: 映射贡献的内部可见截止时间。
- `visibility_policy`: `EXPLICIT_DEADLINE`、`DEFAULT_180_DAYS` 或 `MANUAL_OVERRIDE`。
- `archived_at`: 软归档时间。
- `archive_reason`: `DEADLINE_EXPIRED`、`STALE_180D`、`MANUAL` 或 `REJECTED`。

首次持久化机会时按以下顺序计算：

1. 有可靠的 `application_deadline_at` 时，直接使用该时间并标记 `EXPLICIT_DEADLINE`。
2. 否则使用 `SourceItem.published_at + timedelta(days=180)`。
3. 缺少发布时间时使用 SourceItem 首次采集时间，即不可变的 `SourceItem.created_at + timedelta(days=180)`。

`visibility_until_at` 不写入 FactSet 的 `deadline`，也不在用户简报中称为活动截止日期。普通映射的读取谓词为：分析成功、属于 SourceItem 最新成功版本、未软归档、已到申请开始时间（若存在），且 `now < visibility_until_at`。在 `now >= visibility_until_at` 时，到期任务写入软归档原因；读取谓词本身也检查时间，因此即使任务延迟也不会继续展示过期边。

同一 SourceItem 的新 DocumentVersion 不重置发布时间或首次采集时间，只由最新成功版本贡献映射；一篇全新的 SourceItem 独立计算自己的有效期。这样既保留版本审计，也避免重新抓取或重新解析无意延长 180 天。

### 6. 软归档按贡献者生效

一个聚合边只要还有至少一个当前有效贡献就继续存在。某个 ArticleOpportunity 到期时只移除它自己的贡献；官方贡献或其他文章贡献仍有效时不影响用户边。当最后一个贡献失效时，边才从当前树消失。

手动提前归档设置 `archive_reason=MANUAL`。延长操作必须给出新的未来 `visibility_until_at`，设置 `MANUAL_OVERRIDE` 并清除归档字段。恢复尚未到期的手动归档可以直接清除归档；恢复已到期记录时必须同时给出新的未来时间，避免任务立即再次归档。所有操作写入现有 ReviewDecision/操作审计机制。

选择贡献者级软归档而不是删除机会或边，是为了让文章事实、简报和证据始终可回查，并避免同边多来源相互误伤。

### 7. StatusMatch 关联文章回到纯 highlights，兼容历史数据

StatusMatch article prompt、验证和工作流停止要求、物化和比较 `candidate_status_mappings`；新 supplement 只按 highlights 决定结果。对外 composed brief 不再返回 mapping claims，图服务删除候选/批准图层和审批入口。

为保证已经成功处理的文章幂等重跑仍为零模型调用，既有 prompt/input-version 不因本次清理而强制失效；兼容解析可以接受历史结果中的旧候选字段，但运行时必须忽略它。数据库中既有 `mapping_claims` 列与历史值本次不做破坏性删除，只作为不可消费的遗留审计数据保留。后续若要物理清理，必须单独提出带备份和回滚方案的迁移。

这种渐进停用比立即删列更安全：它实现了用户和运行时边界，又不会因为模式切换重跑 AI 或丢失已采集证据。

### 8. 不增加 AI 调用和关系阶段

普通文章映射直接复用正文一次结构化理解已写入 FactSet 的 `status_mappings`；树构建、规范化、生命周期和聚合全部为确定性代码。文章 Brief 仍是每个新增或实质变化机会的第二次调用。StatusMatch 关联文章仍只有既有 highlights 调用，且减少候选映射指令。

任何实现不得调用 CandidateRetriever、EventRelationshipAnalyzer、EventAggregator 或新增“统一树 AI”。完全相同输入重跑必须保持零模型调用。

## Risks / Trade-offs

- [不同来源对同一边给出不同条件] → 用户仍只看到一条边，但展示去重后的条件变体并采取保守的 conditional 标记；管理员审计保留每个贡献，普通文章自身冲突的声明不发布。
- [别名误归一导致错误去重] → 复用现有可解释别名规则；歧义保持为独立节点并进入审计，不猜测合并。
- [到期任务延迟] → 用户读取同时执行 `now < visibility_until_at`，任务仅负责持久化归档状态和统计。
- [历史 `mapping_claims` 被旧入口再次消费] → 删除/禁用候选层、审批服务和对外字段，并以架构测试禁止 StatusMatch supplement 进入统一贡献适配器。
- [统一读取比官方图查询更昂贵] → 仅读取当前 FactSet 和每个 SourceItem 最新成功分析，使用有效期/状态索引；先在读取时构建，达到可观测瓶颈后才考虑不改变语义的缓存。
- [180 天被误解为活动截止] → 单独命名为 visibility/freshness 字段，禁止回写 FactSet deadline，默认用户简报不展示该时间。

## Migration Plan

1. 增加普通 ArticleOpportunity 可见期和软归档字段及索引；根据已有明确截止、SourceItem 发布时间或 SourceItem 首次采集时间回填，不删除任何记录。
2. 先实现生命周期谓词、到期任务和手动操作，使过期贡献即使任务延迟也不可见。
3. 提取来源无关的图规范化/遍历组件，实现官方与普通文章贡献适配器以及统一树审计。
4. 对比新服务的“仅官方输入”结果与现有官方树，确认节点、边和遍历拓扑等价后再切换用户 CLI/API。
5. 停止 StatusMatch 关联文章候选映射的生成与消费，隐藏历史 mapping claims；保持历史 supplement 幂等复用。
6. 以 LoyaltyLobby 真实文章和 StatusMatch 官方项目做混合来源、证据、180 天边界与零额外 AI 的人工验收。

回滚时可以把用户 CLI/API 指回现有 `MembershipGraphService`；新增字段和历史数据无需删除。StatusMatch 关联文章若需短期回滚，其旧列仍在，但候选功能只能通过显式代码回滚恢复，不能由数据自动重新启用。

## Open Questions

无阻塞问题。未来若增加 LoyaltyLobby 以外的数据源，只需实现同一普通文章贡献契约；跨来源“同一消息”合并继续作为独立变更处理。
