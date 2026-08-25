## ADDED Requirements

### Requirement: StatusMatch 关联文章只生成项目补充亮点
精确路由到某个 `*.statusmatch.com` 项目的第三方文章 SHALL 只在既有一次结构化补充调用中提取相对当前官方 FactSet 和 Brief 新颖且有原文证据的 highlights；工作流不得要求、生成、比较、批准或发布候选会籍映射。

#### Scenario: 文章同时包含补充关注点和会籍匹配表述
- **WHEN** StatusMatch 关联文章包含有用的新颖关注点以及原等级到目标等级描述
- **THEN** supplement 只保存符合规则的 highlights
- **AND** 不从该文章创建 mapping claim 或图边

#### Scenario: 文章只有会籍匹配表述但无新颖亮点
- **WHEN** 文章没有相对官方产物的新颖 highlights
- **THEN** 新处理结果为成功的无新颖补充
- **AND** 不因会籍描述把结果升级为候选映射结果

### Requirement: 关联文章不得修改 StatusMatch 官方权威产物
StatusMatch 关联文章 SHALL 仅作为绑定项目详情的补充材料，且不得修改官方 FactSet、官方 Brief、官方 status_mappings、官方 change set、watch/event 状态或官方图输入；官方项目生命周期继续只由现有 HOME+FAQ 监控决定。

#### Scenario: 关联文章与官网说法不同
- **WHEN** 第三方文章的会籍表述与当前官方 FactSet 不一致
- **THEN** 官方 FactSet、Brief 和图不发生变化
- **AND** 文章只可按 highlights 规则保留有用的关注点

#### Scenario: 官方项目归档
- **WHEN** 现有 StatusMatch 监控归档项目
- **THEN** 官方边按现有生命周期从当前官方图移除
- **AND** 历史文章 routes 和 supplements 仍可随归档 event 审计

### Requirement: 关联文章不适用普通文章 180 天映射规则
StatusMatch 关联文章 SHALL 不创建 ArticleOpportunity 映射贡献，因此 SHALL 不计算、继承或覆盖普通文章的 `visibility_until_at`，也不得以文章日期控制官方映射边；其 highlights 继续按绑定项目的当前/历史 composed read 规则展示。

#### Scenario: 关联文章没有截止日期
- **WHEN** 一篇 StatusMatch 关联文章没有写申请截止日期
- **THEN** 系统不为它创建 180 天映射有效期
- **AND** 它对统一树始终为零贡献

#### Scenario: 关联文章写了更早截止日期
- **WHEN** 文章给出一个早于官网项目生命周期的日期
- **THEN** 该日期不得提前撤销或修改官方映射边
- **AND** 只可作为有证据且新颖的补充关注点展示

### Requirement: 历史候选映射数据停用但不破坏删除
系统 SHALL 停止读取和写入 StatusMatchArticleSupplement 的候选/批准映射能力，默认 composed brief、用户树、官方图和统一树 SHALL 忽略历史 `mapping_claims`；既有列和值本次 SHALL 保留为不可消费的兼容审计数据。

#### Scenario: 数据库已有历史 mapping claims
- **WHEN** 升级前的 supplement 含有 candidate、conflicting 或 approved claim
- **THEN** 升级后这些 claim 不得产生任何当前图层或树边
- **AND** 原始持久化值不被本次迁移删除

#### Scenario: 查询 composed brief
- **WHEN** 用户读取包含历史 mapping claims 的 StatusMatch 项目
- **THEN** 默认 supplement 合同只返回 highlights 及文章信息
- **AND** 不返回候选映射、批准状态或第三方图层标识

#### Scenario: 旧审批入口
- **WHEN** 调用方尝试批准或拒绝历史第三方 mapping claim
- **THEN** 运行时不再暴露该业务操作

### Requirement: 清理边界不得强制重跑 AI
工作流 SHALL 复用相同 route、DocumentVersion、官方 FactSet、官方 Brief 和 provider 配置下既有成功 supplement 或无新颖结果；兼容读取旧结构时 SHALL 忽略候选字段而不得仅因候选能力停用产生新的模型调用。

#### Scenario: 既有成功文章完全重跑
- **WHEN** 输入事实、Brief、文章版本和 provider 配置均未变化
- **THEN** 工作流复用原 supplement
- **AND** 模型调用新增数为零

#### Scenario: 官方 FactSet 实质更新
- **WHEN** 绑定项目产生新的当前官方 FactSet 或 Brief
- **THEN** 文章仍可按既有规则进行一次新的 highlights 对比
- **AND** 新输出不包含候选会籍映射

### Requirement: StatusMatch 官方调用和结果保持回归稳定
移除关联文章候选映射后，StatusMatch HOME+FAQ 官方处理的 FactSet、Brief、mapping graph 和正常模型调用次数 SHALL 与变更前保持一致；关联文章补充仍为至多一次正常 AI 调用，有限纠错重试除外。

#### Scenario: 运行官方项目工作流
- **WHEN** 使用同一 HOME+FAQ 输入处理 StatusMatch 项目
- **THEN** 官方 FactSet 和 Brief 合同及调用阶段不变
- **AND** 不读取任何普通 ArticleOpportunity

#### Scenario: 处理新的关联文章
- **WHEN** 官方项目已准备完成且新文章需要补充对比
- **THEN** 正常路径只产生一次 highlights 结构化调用
- **AND** 不产生分类、关系、事实合并、mapping 审核或图 AI 调用

