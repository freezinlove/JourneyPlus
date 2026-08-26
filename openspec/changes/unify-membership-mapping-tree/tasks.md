## 1. 固化回归基线与公共契约

- [x] 1.1 为现有 `MembershipGraphService` 增加仅官方输入的拓扑快照回归夹具，记录代表性 exact、conditional、wildcard、uncertain、多跳和循环结果，确保后续重构不改变 StatusMatch 官方图语义。
- [x] 1.2 在 `journeyplus.membership` 中定义来源无关的 `MembershipMappingContribution`、贡献来源、可见区间、内部 provenance 以及统一图审计合同，避免包含 LoyaltyLobby 或 StatusMatch 工作流专属调用。
- [x] 1.3 定义默认用户树合同与管理员贡献审计合同：用户合同不含 official/third-party 标识和 contributor 列表，管理员合同保留 DocumentVersion、FactSet、证据、来源和生命周期。
- [x] 1.4 增加架构测试，禁止 StatusMatch 官方工作流导入普通文章处理服务、禁止普通文章工作流导入 StatusMatch 项目服务，并限定只有统一读取层可以组合两个贡献适配器。

## 2. 普通文章可见期数据与迁移

- [x] 2.1 新增 `0011` 非破坏性迁移，为 `article_opportunities` 增加 `visibility_until_at`、`visibility_policy`、`archived_at`、`archive_reason` 及当前可见查询索引，不重写已存在的 `0010`。
- [x] 2.2 在迁移中按“明确 application deadline → SourceItem published_at + 180 天 → SourceItem created_at + 180 天”回填已有机会，并用迁移测试覆盖 SQLite 测试数据库的 upgrade/downgrade 与数据保留。
- [x] 2.3 更新 `ArticleOpportunityRecord` 及内部枚举/校验，限制策略为 `EXPLICIT_DEADLINE`、`DEFAULT_180_DAYS`、`MANUAL_OVERRIDE`，归档原因为 `DEADLINE_EXPIRED`、`STALE_180D`、`MANUAL`、`REJECTED`。
- [x] 2.4 在 ArticleOpportunity 首次持久化时确定性计算可见截止和策略，复用规范化后的明确截止时间；默认 180 天严格使用 `timedelta(days=180)` 且不得写入 FactSet deadline 或 Brief 输入。
- [x] 2.5 实现单一 `is_mapping_visible(opportunity, analysis, source_item, now)` 谓词，检查最新成功分析、申请开始时间、可见截止和软归档，供统一树与自动化共同复用。

## 3. 生命周期自动化与人工操作

- [x] 3.1 扩展文章生命周期任务，在 `now >= visibility_until_at` 时按策略软归档贡献并写入 `DEADLINE_EXPIRED` 或 `STALE_180D`，同时保留现有业务 lifecycle status 计算。
- [x] 3.2 让统一树读取即使在生命周期任务延迟时也排除已到可见截止的贡献，并为扫描数、到期归档数、已归档保留数和失败数增加自动化统计。
- [x] 3.3 在 `article_operations.py` 与 CLI/内部操作接口实现手动提前归档，写入 `MANUAL`、操作者、原因及 ReviewDecision 前后值。
- [x] 3.4 实现恢复与延长：尚未到期的 MANUAL 归档可恢复；已到期记录必须提供新的未来时间；延长设置 `MANUAL_OVERRIDE` 并清除归档字段。
- [x] 3.5 增加时区和精确边界测试，覆盖 2026-08-24 10:00 加 180 天等于 2027-02-20 10:00、第 179 天可见、第 180 天边界隐藏、明确截止优先和发布时间缺失回退首次采集时间。

## 4. 两类映射贡献适配器

- [x] 4.1 实现 `StatusMatchOfficialContributionAdapter`，只读取 ACTIVE watch 当前 event 的当前 FactSet，并将 AVAILABLE、CONDITIONAL、wildcard/uncertain 规则及官方证据转换为来源中立贡献。
- [x] 4.2 实现 `OrdinaryArticleContributionAdapter`，只查询每个 SourceItem 最新成功 ArticleAnalysis 下当前可见的机会，从现有 FactSet `status_mappings` 生成具体直接贡献。
- [x] 4.3 在普通文章适配器中防御性排除存在 `StatusMatchArticleRoute` 的 DocumentVersion，并排除 UNAVAILABLE、`conflict=true`、无证据、结构无效和非成功分析的映射。
- [x] 4.4 为同一 SourceItem 新 DocumentVersion 增加回归：最新成功版本取代旧版本成为当前贡献，但 published_at/首次采集起点和默认 180 天不得因重抓取或重解析重置。
- [x] 4.5 为全新 SourceItem 增加独立有效期测试，证明相同映射的新文章无需事件关系判断即可重新贡献，并确认未调用 CandidateRetriever、EventRelationshipAnalyzer 或 EventAggregator。

## 5. 统一图构建与有界树遍历

- [x] 5.1 从 `statusmatch/graph.py` 提取来源无关的程序/等级规范化、别名歧义、邻接表和有界遍历组件，并让现有官方图服务复用它通过基线回归。
- [x] 5.2 实现 `UnifiedMembershipTreeService`，组合官方与普通文章适配器，以规范化起点节点和终点节点为边键进行确定性聚合，不持久化最终边或传递边。
- [x] 5.3 聚合同边的 contributor、证据、条件变体、certainty 和有效期：默认用户输出只返回一条来源中立边，管理员审计返回所有独立贡献且不覆盖原始事实。
- [x] 5.4 复用 CYCLE、CROSS_REFERENCE、`max_depth`、`max_nodes` 和 `max_branches` 语义，覆盖官方 A→B/文章 B→C、文章 A→B/官方 B→C 两种混合多跳，并断言不存在 A→C 直接边。
- [x] 5.5 实现统一图 fidelity/topology 审计，分别报告被排除的 unavailable、conflicting、ungrounded、expired、archived 和 ambiguous 贡献，同时保持官方审计 expected claim 集合不变。
- [x] 5.6 将面向用户的 membership tree CLI 和 review API 切换为 `UnifiedMembershipTreeService`，保留显式官方审计入口和管理员统一贡献审计入口。

## 6. StatusMatch 关联文章恢复为纯补充

- [x] 6.1 从 StatusMatch article 系统提示、请求规则、纠错提示和新结果校验中移除候选会籍映射要求；保留对历史 `candidate_status_mappings` 字段的只读兼容并在运行时忽略。
- [x] 6.2 停止 `_materialize_mapping_claims`、官方关系比较和新 supplement `mapping_claims` 写入，新结果状态只由 highlights 决定，且正常路径仍至多一次补充 AI 调用。
- [x] 6.3 从默认 `ComposedStatusMatchBrief`/supplement view 中移除 mapping claims，确认文章只作为 highlights 补充，不修改官方 FactSet、Brief、change set、watch/event 或图输入。
- [x] 6.4 移除或禁用 candidate/approved graph layer、第三方 claim approve/reject 操作及其 CLI/API 暴露；保留数据库历史列和值但保证所有当前图服务均不消费。
- [x] 6.5 增加历史兼容测试：已有 CANDIDATE、CONFLICTING、APPROVED 数据升级后不产生任何树边，既有成功 supplement 在相同输入完整重跑时新增模型调用为零。
- [x] 6.6 增加官方 StatusMatch 回归，断言相同 HOME+FAQ 的官方 FactSet、Brief、status mappings、官方图拓扑和官方模型调用阶段不因本变更改变。

## 7. 聚合边与发布策略测试

- [x] 7.1 覆盖官方单边、普通文章单边、官方与文章相同边只显示一次，并在管理员审计中验证两个 contributor 和各自证据完整保留。
- [x] 7.2 覆盖同边一项贡献到期但其他贡献仍有效、两篇文章期限不同、最后一个贡献到期后边消失，以及手动归档/恢复只影响目标 contributor。
- [x] 7.3 覆盖同一边具有不同条件变体、普通文章自身冲突被排除、UNAVAILABLE 不可遍历、别名歧义不猜测合并和循环查询有限结束。
- [x] 7.4 覆盖用户与管理员读取相同拓扑但默认用户合同无来源等级字段，并验证 180 天内部时间不出现在 FactSet deadline 或用户 Brief。
- [x] 7.5 覆盖完全幂等重跑：标题筛选、正文分析、ArticleOpportunity、Brief、StatusMatch supplement、生命周期和统一树均无输入变化时，本变更新增 AI 调用为零。

## 8. LoyaltyLobby 真实数据与人工验收

- [x] 8.1 仅启用 LoyaltyLobby 普通来源，收集并处理 2026-08-24 的文章集，记录每篇标题筛选、正文调用、机会数、Brief 调用、直接映射、可见策略和模型调用总数。
- [x] 8.2 使用 8 月 24 日正例验证普通文章直接映射进入统一树；若该日不能覆盖无截止日期、明确截止、同边去重、混合多跳或负例，自行选择最少数量的其他 LoyaltyLobby 文章补齐场景。
- [x] 8.3 人工打开并阅读每篇验收原文，将输出中的原项目、原等级、目标项目、目标等级、条件、截止日期和每条证据逐项与原文对比，不得只依据自动测试通过判定正确。
- [x] 8.4 选择至少一个精确链接 StatusMatch 项目的 LoyaltyLobby 文章，人工确认其最终只出现在项目 highlights 中、对统一树零贡献、没有 180 天映射字段且官方 FactSet/Brief 未被修改。
- [x] 8.5 保存真实验收报告，列出文章 URL、DocumentVersion、各直接贡献、树路径、生命周期计算、原文定位、人工判断、额外 AI 调用数和未覆盖风险。

## 9. 全量验证与交付

- [x] 9.1 运行迁移、生命周期、普通文章、StatusMatch article、官方图、统一树、CLI/API、自动化、初始化、架构和全量测试，修复所有由本变更引起的回归。
- [x] 9.2 运行格式化、静态检查和 OpenSpec 严格校验，确认任务、设计和三份规格一致，且没有跨文章合并、关系 AI 或额外图 AI 的实现。
- [x] 9.3 记录部署/回滚步骤：先迁移与回填、再启用生命周期、对比仅官方投影、切换用户树、最后停用历史候选入口；回滚只需把用户入口指回官方图且不删除新增或历史数据。
