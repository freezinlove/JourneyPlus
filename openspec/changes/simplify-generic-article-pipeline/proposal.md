## Why

当前通用文章链路把全文分类、事件候选召回、关系判断、跨材料事实整理和简报生成串成多个 AI 阶段；一篇命中文章通常需要三至四次调用，历史材料还会在关系与事实阶段被重复发送。现阶段通用来源只需要开放 LoyaltyLobby，没有跨来源事件合并需求，因此应先把链路收缩为文章级独立处理，并为将来的独立关联能力保留稳定数据出口。

## What Changes

- **BREAKING**：通用公开文章来源暂时只开放 `loyaltylobby_feed`；`status_services_mail` 继续只服务现有 StatusMatch 专用链路，其他公开来源保留适配器与历史数据但退出自动采集和通用处理。
- 为 LoyaltyLobby 新文章增加高召回的批量标题筛选；每批标题一次 AI，只有高置信度无关项停止，可能相关、无法判断或筛选失败的项继续读取正文。
- 将最终分类、文档内活动拆分、活动核心字段、文章事实与原文证据合并为一次正文结构化提取；不再为同一文章另做全文分类和 AI 事实整理。
- **BREAKING**：通用链路不再召回候选事件、不调用关系 AI、不判断 `SAME_EVENT / UPDATE_OF`，也不跨文章自动合并或聚合事实。每份文章版本产生独立、可审计的文章分析和一个或多个 `ArticleOpportunity`。
- 文章事实快照通过程序完成证据绑定、规范化与校验；中文简报保留为事实快照之后的第二次独立 AI 调用，事实签名未变化时复用已有简报。
- 精确包含项目专属 `*.statusmatch.com` 链接的 LoyaltyLobby 文章继续确定性路由到 StatusMatch 第三方补充链路，不进入通用标题筛选或文章机会处理。
- 扩展 StatusMatch 第三方文章现有单次 AI 输出，使其在补充亮点之外可返回结构统一、来源独立的候选会籍匹配声明；候选声明不得写入官方 FactSet，也不得未经确认成为官方匹配图的可遍历边。
- 保存足以支持未来实体关联/记录链接的稳定文章机会字段和不可变来源事实，但本变更不实现候选生成、相似度评分、聚类、关联表或空的关系解析器。

## Capabilities

### New Capabilities

- `generic-article-screening`: 限定通用来源、执行确定性专用路由，并以批量标题高召回筛选控制正文 AI 入口。
- `article-opportunity-processing`: 用一次正文 AI 产生独立文章机会与事实快照，禁止跨文章关联，并按事实版本幂等生成简报。
- `third-party-membership-mapping-claims`: 在 StatusMatch 第三方文章单次补充分析中提取带来源和审核状态的候选会籍匹配声明，并与官方 FactSet 和主图隔离。

### Modified Capabilities

<!-- 当前仓库没有已同步到 openspec/specs/ 的主规格；本变更以新能力描述替代通用 V1 行为。 -->

## Impact

- 影响每日自动编排中的来源选择、文档路由、通用待处理文档选择和模型调用预算。
- 新增标题批次筛选、文章级结构化提取、文章机会/事实快照持久化及相应分析阶段与幂等键。
- LoyaltyLobby 不再调用现有 `StatusRelevanceAnalyzer`、`CandidateRetriever`、`EventRelationshipAnalyzer` 和跨文章 `FactConsolidator`；旧 V1 在切换验证完成前保留以支持影子比较和回滚。
- 需要让文章简报以文章机会事实快照为输入，同时保持 StatusMatch 官方项目的现有两次 AI 链路、数据结构、监控和输出行为不变。
- 影响 StatusMatch 第三方补充契约、持久化结果和匹配图读取边界，但不修改官方 StatusMatch FactSet 或官方图的默认权威语义。
- 不引入向量数据库、图数据库、外部关联服务或新的常驻调度平台。
