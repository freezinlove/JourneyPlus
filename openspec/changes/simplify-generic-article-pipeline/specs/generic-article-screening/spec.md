## ADDED Requirements

### Requirement: 通用来源边界
系统 SHALL 只把 `loyaltylobby_feed` 作为当前通用文章链路的公开来源；`status_services_mail` SHALL 继续只进入 StatusMatch 专用发现与项目处理链路，其他公开来源 SHALL 保留适配器和历史原文但不得被自动采集或送入通用处理。

#### Scenario: 每日运行只选择 LoyaltyLobby 通用来源
- **WHEN** 每日自动运行选择到期的公开来源
- **THEN** 通用采集和文章处理只选择 `loyaltylobby_feed`
- **AND** `status_services_mail` 只由 StatusMatch 专用处理器消费
- **AND** 其他公开来源不产生新的自动采集或通用处理任务

#### Scenario: 已有其他来源历史数据被保留
- **WHEN** 通用来源策略收缩到 LoyaltyLobby
- **THEN** 系统不得删除或覆盖其他来源的注册信息、SourceItem、DocumentVersion 或历史派生结果
- **AND** 这些来源保持不可自动调度和不可进入通用 V2

### Requirement: 专用文章确定性路由
系统 SHALL 在标题筛选前检查 LoyaltyLobby 当前文档中的精确项目专属 `*.statusmatch.com` 链接，并把命中的文章仅路由到 StatusMatch 第三方补充链路；通用文章处理模块不得直接依赖或调用 StatusMatch 工作流。

#### Scenario: 含精确 StatusMatch 项目链接
- **WHEN** LoyaltyLobby 文档包含受支持的精确项目专属 `*.statusmatch.com` 链接
- **THEN** 自动编排层把文档路由到 StatusMatch 第三方补充处理器
- **AND** 文档不进入通用标题筛选、正文文章机会提取或通用简报生成

#### Scenario: 不含 StatusMatch 项目链接
- **WHEN** LoyaltyLobby 文档不包含受支持的精确项目专属链接
- **THEN** 自动编排层把文档路由到通用标题筛选

#### Scenario: 通用模块保持低耦合
- **WHEN** 检查通用 V2 的模块依赖
- **THEN** 通用 V2 不得导入 `journeyplus.statusmatch` 下的工作流、模型或服务
- **AND** 跨模块选择只发生在自动编排或其他组合入口

### Requirement: 批量标题高召回筛选
系统 SHALL 仅使用稳定文档标识和文章标题对待处理通用文章执行批量结构化筛选；一次模型调用 SHALL 处理一个受配置容量限制的标题批次，并为每项返回 `PASS`、`DROP` 或 `NEEDS_BODY`。

#### Scenario: 多篇新文章合并为一个标题批次
- **WHEN** 同一轮存在多篇尚无当前版本筛选结果的 LoyaltyLobby 普通文章
- **THEN** 系统在配置的批次容量内用一次模型调用提交多个标题
- **AND** 请求不得包含任何文章正文
- **AND** 输出通过稳定文档标识逐项对应输入

#### Scenario: 明确无关标题停止处理
- **WHEN** 某标题被模型以满足配置阈值的高置信度判为 `DROP`
- **THEN** 系统记录筛选原因并停止该文档的正文 AI 处理

#### Scenario: 可能相关标题继续处理
- **WHEN** 某标题被判为 `PASS` 或 `NEEDS_BODY`
- **THEN** 系统把该文档送入正文文章机会处理

#### Scenario: 低置信度 DROP 保守升级
- **WHEN** 模型返回 `DROP` 但置信度低于配置阈值
- **THEN** 系统 SHALL 把结果规范化为 `NEEDS_BODY`
- **AND** 不得仅凭该结果丢弃文章

### Requirement: 标题筛选失败安全与幂等
标题筛选 SHALL 以规范化标题哈希、提示词版本、Schema 版本和模型配置版本形成可重放的幂等输入；筛选调用或结构校验失败 SHALL 保守允许正文处理，而不是把文章视为无关。

#### Scenario: 相同标题筛选重跑
- **WHEN** 相同标题和相同筛选版本再次进入处理
- **THEN** 系统复用既有逐文档筛选结果
- **AND** 不产生新的模型调用

#### Scenario: 标题筛选批次失败
- **WHEN** 批次模型调用失败或输出不能完整映射到输入文档
- **THEN** 未获得有效结果的文档被记录为 `NEEDS_BODY`
- **AND** 后续正文处理仍可继续
- **AND** 已成功持久化的其他文档结果保持可复用

### Requirement: 标题筛选上线阶段门
系统 SHALL 在标题筛选真正阻断正文处理前，以影子模式对冻结金标和 LoyaltyLobby 历史样本验证高召回边界；任何已知正例不得被有效 `DROP`。

#### Scenario: 影子验证发现正例被丢弃
- **WHEN** 已知 `STATUS_OPPORTUNITY` 正例被标题筛选判为满足阈值的 `DROP`
- **THEN** 标题阻断能力不得启用
- **AND** 系统记录案例并调整提示词、阈值或守卫后重新全量验证

#### Scenario: 影子验证通过
- **WHEN** 冻结正例全部落入 `PASS` 或 `NEEDS_BODY` 且批次输出完整可重放
- **THEN** 系统可以在 LoyaltyLobby 通用 V2 中启用高置信度 `DROP` 阻断

