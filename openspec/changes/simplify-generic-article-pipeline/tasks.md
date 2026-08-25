## 1. 现状基线与边界守卫

- [x] 1.1 为当前 LoyaltyLobby V1 与 StatusMatch 官方/第三方链路保存调用阶段、幂等和输出基线，覆盖单机会、多机会、无关文章和精确 StatusMatch 路由
- [x] 1.2 增加架构守卫测试，确保新 `article_pipeline` 不导入 `journeyplus.statusmatch`，跨模块路由只在自动编排组合入口发生
- [x] 1.3 增加行为守卫测试，确保通用 V2 不调用 `CandidateRetriever`、`EventRelationshipAnalyzer`、跨文章 `EventAggregator` 或 `FactConsolidator`
- [x] 1.4 明确自动运行模型调用统计口径，分别记录标题批次、正文理解、文章简报、StatusMatch 项目和 StatusMatch 第三方补充调用

## 2. 文章级契约与持久化

- [x] 2.1 新增标题筛选、`ArticleInterpretation`、`ArticleOpportunity`、文章事实快照和逐字文章证据的严格结构化契约及交叉字段校验
- [x] 2.2 新增 `ArticleAnalysisRecord`、`ArticleOpportunityRecord` 和 `ArticleBriefRecord` ORM 模型、唯一约束、索引和 PostgreSQL 迁移
- [x] 2.3 实现 SourceItem 最新成功文章分析读取和 DocumentVersion 历史审计查询，验证新版本不会覆盖旧分析或机会
- [x] 2.4 为 opportunity ID、正文输入版本、事实物质签名和文章简报输入版本增加稳定计算与幂等测试
- [x] 2.5 保存未来关联所需的来源、文档、canonical URL、发布时间、项目、目标等级、摘要、窗口、行动链接、事实、证据和内容签名，不增加 group、候选或关系字段

## 3. 批量标题筛选

- [x] 3.1 实现只接受稳定文档 ID 与标题的批量结构化筛选服务，支持配置化批次容量、`PASS / DROP / NEEDS_BODY` 和逐项结果映射
- [x] 3.2 实现规范化标题哈希、模型/提示词/Schema 版本幂等、逐文档结果持久化和相同输入零调用重跑
- [x] 3.3 实现高置信度 DROP 阈值、低置信度保守升级以及批次失败、缺项、重复 ID 和结构失败时的 `NEEDS_BODY` 放行
- [x] 3.4 增加单项、多项、跨批次、部分失败、完全失败、幂等和“筛选请求不含正文”的自动化测试
- [x] 3.5 增加标题筛选影子运行和报告入口，对冻结金标与 LoyaltyLobby 历史样本报告正例 DROP、各决策数量、批次调用数和复用数

## 4. 一次正文文章机会提取

- [x] 4.1 实现一次完成最终分类、文档内机会拆分、核心身份、事实、申请路径、活动窗口、行动链接和证据别名的正文提示词与结构化 Provider 调用
- [x] 4.2 实现 `NONE` 无机会、`STATUS_OPPORTUNITY` 至少一个机会、`UNCERTAIN` 不发布以及多机会局部索引和字段隔离校验
- [x] 4.3 实现文章证据别名解析、DocumentVersion/URL 注入、逐字 quote 验证、行动链接白名单和跨机会串线拒绝
- [x] 4.4 实现单文档事实规范化、未知字段守卫、北京时间日期和生命周期计算、事实物质签名，不读取其他文章或事件材料
- [x] 4.5 实现有界纠错重试、安全诊断、失败后待处理状态和成功结果持久化；相同正文版本重跑复用现有分析
- [x] 4.6 增加单机会、多机会、混合文章、NONE、UNCERTAIN、缺失字段、无效引用、串线、重试和零调用重跑测试

## 5. 文章机会简报

- [x] 5.1 抽取可复用的 Brief 输出契约、已知/未知字段守卫、来源白名单和 grounding 校验，同时保持现有 StatusMatch `BriefGenerator` 行为不变
- [x] 5.2 实现以 ArticleOpportunity 事实快照为唯一输入的文章简报生成与 `ArticleBriefRecord` 持久化，不把正文或其他文章传给简报模型
- [x] 5.3 实现按 opportunity ID、事实签名、模型、提示词和 Schema 版本的简报幂等与事实不变复用
- [x] 5.4 实现简报失败不回滚文章分析和事实、独立重试及多机会文章局部失败隔离
- [x] 5.5 增加单机会两次总调用、多机会一次正文加每机会一次简报、事实不变零简报调用和无依据输出拒绝测试

## 6. 来源策略、确定性路由与 V2 编排

- [x] 6.1 将自动来源策略配置为通用只开放 `loyaltylobby_feed`、专用保留 `status_services_mail`，关闭其他公开来源自动调度和 V2 选择但不删除注册与历史数据
- [x] 6.2 在组合入口实现标题筛选前的精确项目专属 `*.statusmatch.com` 检测，使命中文档只进入 StatusMatch 第三方链路
- [x] 6.3 实现 LoyaltyLobby 普通文档的 V2 待处理选择、标题批次、正文任务、事实保存和简报任务编排及各阶段积压统计
- [x] 6.4 替换 V1 整条 fingerprint 为阶段独立幂等键，验证单个提示词或 Schema 升级只重跑受影响阶段
- [x] 6.5 增加同文路由互斥、其他来源不入队、邮件不入通用链路、来源失败隔离、模型调用预算和完整重跑零调用测试

## 7. 第三方会籍匹配声明

- [x] 7.1 在中立 `membership` 领域模块定义统一映射核心、provenance 和 `CORROBORATED / CANDIDATE / CONFLICTING / REJECTED / APPROVED` 状态契约
- [x] 7.2 扩展 StatusMatch 第三方文章现有输出，在同一次 AI 调用中返回 `highlights` 与 `candidate_status_mappings`，并保持旧亮点结果兼容
- [x] 7.3 实现第三方关系逐字引用校验、route/project/event/文章文档/对照 FactSet 来源包装和独立持久化
- [x] 7.4 实现只接受直接映射的守卫，拒绝缺字段、策略性推测和由 `A → B → C` 发明的 `A → C` 直接关系
- [x] 7.5 实现候选关系与当前官方 `status_mappings` 的确定性等价、缺失和冲突比较，并支持官方 FactSet 更新后的重新对照
- [x] 7.6 实现显式候选图查询以及窄的人工批准/拒绝服务；默认官方图继续只读取 ACTIVE 项目当前官方 FactSet
- [x] 7.7 增加单次调用、零关系、直接关系、多跳拒绝、官方佐证、官网缺失、冲突、FactSet 隔离、候选图和批准关系图策略测试

## 8. 影子验证与切换

- [x] 8.1 对冻结金标和 LoyaltyLobby 历史材料运行标题影子评测，确认所有已知正例均为 `PASS` 或 `NEEDS_BODY` 后记录启用阈值与批次容量
- [x] 8.2 对同一批 LoyaltyLobby 文章影子运行 V1 与 V2，比较最终标签、文档内机会数、事实、证据、简报、模型调用数和正文输入规模
- [x] 8.3 逐项修复正例漏失、机会串线、无证据事实、无依据简报、额外关系/事实 AI 调用和非幂等问题，并全量回归
- [x] 8.4 在影子阶段门通过后把 LoyaltyLobby 普通文章切换到 V2，保留 V1 历史结果和可配置回滚入口但停止新文档自动进入 V1
- [x] 8.5 验证 StatusMatch HOME + FAQ 仍保持初次两次调用、语义不变时事实与简报复用，第三方补充除有限重试外仍为一次调用

## 9. 完整验证与运维交接

- [x] 9.1 运行文章 V2、来源、自动化、生命周期、复核、StatusMatch 项目、第三方补充、匹配图和完整测试套件
- [x] 9.2 验证 SQLite 测试迁移和 PostgreSQL 升级/回滚边界，确认迁移不删除旧来源、原文、V1 事件、FactSet 或 Brief
- [x] 9.3 运行 `openspec validate simplify-generic-article-pipeline --strict` 并修复全部规格错误
- [x] 9.4 使用受控真实 LoyaltyLobby 批次验证标题筛选、路由互斥、正文证据、文章机会、事实、简报、调用预算和第二次运行幂等
- [x] 9.5 更新架构、CLI、自动运行状态和运维文档，说明当前不做跨文章关联、其他来源关闭、回滚方式及未来分组投影的数据接口
- [x] 9.6 观察短期自动运行，确认没有正文正例误筛、重复业务记录、额外关系/事实调用、跨机会串线或 StatusMatch 回归后记录验收结论
