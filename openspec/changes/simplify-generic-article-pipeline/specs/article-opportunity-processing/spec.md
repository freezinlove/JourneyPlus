## ADDED Requirements

### Requirement: 一次正文结构化理解
通过标题筛选的普通文章 SHALL 只用一次正文 AI 调用完成最终单标签判断、文档内独立机会拆分、机会核心字段、完整文章事实和原文证据提取；后续阶段不得为同一文章再次调用全文分类或 AI 事实整理。

#### Scenario: 一篇文章包含一个机会
- **WHEN** 正文明确包含一个会籍获取机会
- **THEN** 一次结构化输出返回 `STATUS_OPPORTUNITY` 和一个 `ArticleOpportunity`
- **AND** 该机会包含项目、目标等级、摘要、可用活动窗口、行动链接、事实字段和文章证据

#### Scenario: 一篇文章包含多个独立机会
- **WHEN** 正文明确包含多个目标项目或独立行动入口对应的现实机会
- **THEN** 同一次结构化输出返回多个按文档局部索引标识的 `ArticleOpportunity`
- **AND** 各机会的时间、资格、费用、入口和证据不得互相串线

#### Scenario: 正文最终判为无关
- **WHEN** 标题通过筛选但正文不包含符合业务定义的会籍机会
- **THEN** 输出标签为 `NONE`
- **AND** 输出不得包含任何 `ArticleOpportunity`
- **AND** 系统不生成文章事实快照或简报

#### Scenario: 正文判断不确定
- **WHEN** 正文证据不足以可靠选择正例或无关
- **THEN** 输出标签为 `UNCERTAIN`
- **AND** 系统保留分析结果供复核
- **AND** 不得自动补猜事实或创建已发布简报

### Requirement: 文章内证据绑定与校验
正文模型 SHALL 以文章内证据别名、短定位和逐字引用表达依据；服务层 SHALL 确定性注入当前 DocumentVersion 与 canonical URL，并验证引用真实存在于当前规范化正文。

#### Scenario: 有效文章证据
- **WHEN** 模型返回的事实引用逐字存在于当前正文且属于对应文章机会
- **THEN** 服务层把证据转换为包含 `document_version_id`、`source_url` 和定位的标准证据引用

#### Scenario: 引用不存在或跨机会串线
- **WHEN** 事实引用不在当前正文、来源 URL 不匹配或明显属于同文另一项机会
- **THEN** 当前提取不得持久化为成功结果
- **AND** 系统在有限纠错重试后保留失败诊断和待处理状态

### Requirement: 文章机会独立持久化
系统 SHALL 按 DocumentVersion 保存不可变的 `ArticleAnalysis`，并在其下保存零个或多个独立 `ArticleOpportunity`；当前链路不得把不同文章机会写入共享事件或跨文章事实集合。

#### Scenario: 两篇文章描述看似相同的活动
- **WHEN** 两篇 LoyaltyLobby 文章分别提取出相同项目、目标等级或行动链接
- **THEN** 系统仍分别保存两个文章机会
- **AND** 不查询候选事件、不产生关系判断、不自动合并事实或简报

#### Scenario: 同一 SourceItem 产生新文档版本
- **WHEN** 同一来源条目因正文变化产生新的 DocumentVersion
- **THEN** 系统为新版本创建独立文章分析和机会快照
- **AND** 旧版本保持可审计
- **AND** 默认读取使用该 SourceItem 的最新成功分析版本

#### Scenario: 相同文档版本重跑
- **WHEN** 相同 DocumentVersion、正文哈希和分析版本再次处理
- **THEN** 系统复用既有文章分析、机会和事实快照
- **AND** 不产生新的正文模型调用或重复业务记录

### Requirement: 当前链路禁止跨文章关联
通用 V2 SHALL 不实现候选召回、关系模型、相似度评分、聚类、跨文章更新语义或关联审核状态；文章机会记录 SHALL 不包含当前无业务用途的候选事件和分组字段。

#### Scenario: 处理普通命中文章
- **WHEN** 通用 V2 处理一个有效 ArticleOpportunity
- **THEN** 模型调用阶段中不存在 `EVENT_RELATIONSHIP`
- **AND** 系统不调用现有 `CandidateRetriever`、`EventRelationshipAnalyzer` 或跨文章 `EventAggregator`

#### Scenario: 保存未来可消费的数据出口
- **WHEN** ArticleOpportunity 成功持久化
- **THEN** 记录包含稳定 opportunity ID、来源与文档标识、canonical URL、发布时间、项目、目标等级、摘要、活动窗口、行动链接、事实、证据和内容签名
- **AND** 不要求保存 `group_id`、候选 ID、关系类型、关系置信度或关系分析运行 ID

### Requirement: 文章事实快照由程序规范化
系统 SHALL 从单篇文章的结构化输出直接形成该 ArticleOpportunity 的事实快照，并只执行确定性证据注入、字段校验、日期和 URL 规范化、事实签名计算及生命周期计算；不得读取其他文章正文或调用 AI 进行事实协调。

#### Scenario: 创建事实快照
- **WHEN** 一个 ArticleOpportunity 通过结构与证据校验
- **THEN** 系统保存只引用当前 DocumentVersion 的完整事实快照
- **AND** 按北京时间规则从有证据的申请开始和截止值计算 `UPCOMING / ACTIVE / EXPIRED / UNKNOWN`

#### Scenario: 文章缺失事实
- **WHEN** 当前正文没有明确资格、地域、费用、日期或入口
- **THEN** 对应字段保持未知
- **AND** 系统不得从标题、发布时间、其他文章或模型常识补猜

### Requirement: 简报是事实之后的独立第二次 AI
每个通过验证的文章机会 SHALL 从其当前事实快照独立生成中文简报；简报模型不得读取文章全文或其他文章，且事实签名未变化时 SHALL 复用已有简报。

#### Scenario: 新文章机会生成简报
- **WHEN** 新 ArticleOpportunity 的事实快照首次成功保存
- **THEN** 系统使用事实快照执行一次结构化简报调用
- **AND** 简报只陈述事实快照中的已知字段并保留允许的来源链接

#### Scenario: 多机会文章生成简报
- **WHEN** 一次正文分析产生两个有效 ArticleOpportunity
- **THEN** 正文只调用一次 AI
- **AND** 系统分别为两个事实快照生成各自简报

#### Scenario: 事实签名不变
- **WHEN** 重新处理得到的事实物质签名与已有事实快照相同
- **THEN** 系统复用已有简报
- **AND** 不产生新的简报模型调用

#### Scenario: 简报失败不回滚事实
- **WHEN** 简报生成或依据校验失败
- **THEN** 已成功的文章分析、ArticleOpportunity 和事实快照保持持久化
- **AND** 简报可以通过独立幂等任务重试

### Requirement: 通用文章模型调用预算
除有限纠错重试外，单篇普通命中文章 SHALL 只产生一次正文理解调用，并为每个新增或物质变化的文章机会产生至多一次简报调用；当前链路 SHALL 不产生关系或事实协调模型调用。

#### Scenario: 单机会相关文章
- **WHEN** 一篇文章通过标题筛选并提取一个新机会
- **THEN** 该文章产生一次正文调用和一次简报调用

#### Scenario: 标题筛除文章
- **WHEN** 文章被有效高置信度 `DROP`
- **THEN** 该文章不产生正文、关系、事实或简报调用

#### Scenario: 完全幂等重跑
- **WHEN** 标题、DocumentVersion、模型配置、提示词和 Schema 均未变化且既有任务成功
- **THEN** 整条文章链路产生零次模型调用

### Requirement: V2 影子验证与安全切换
系统 SHALL 在 LoyaltyLobby 从 V1 切换到 V2 前，以相同文章集影子比较分类、文档内机会数、事实证据、简报和模型调用；切换不得改变 StatusMatch 官方项目链路。

#### Scenario: 影子结果存在阻塞差异
- **WHEN** V2 出现正例漏失、机会串线、无证据事实、无依据简报或无法解释的输出退化
- **THEN** LoyaltyLobby 不得切换到 V2
- **AND** 系统保留 V1 作为当前处理路径直至修复和回归通过

#### Scenario: LoyaltyLobby 切换完成
- **WHEN** 影子验证和幂等回归通过
- **THEN** LoyaltyLobby 普通文章只进入 V2
- **AND** 旧 V1 保持可回滚但不再为新 LoyaltyLobby 文档自动运行
- **AND** StatusMatch 官方项目与第三方专用处理行为保持独立

