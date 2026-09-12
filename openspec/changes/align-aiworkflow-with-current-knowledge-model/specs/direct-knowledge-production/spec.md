## ADDED Requirements

### Requirement: Use the actual current database contract
ORM、生产输出和迁移入口 SHALL 与当前 `clean_0003` 加已执行手动补丁一致，不恢复旧业务表、旧查询回退或双写，不新增数据库限制。原文、链接和已放松约束 SHALL 保持。

#### Scenario: Production starts against an empty current-schema database
- **WHEN** 当前结构数据库只含来源配置且无旧业务表
- **THEN** 正常生产链能建立目录、活动与知识，不查询 status_events、fact_sets、article_opportunities 或 knowledge_migration_links

#### Scenario: Reproduce the database baseline
- **WHEN** 从空 PostgreSQL 建立用于实施验收的数据库
- **THEN** 生成的表字段及约束等价于当前实际基线，包含价格说明默认值与六项放松，不因迁移版本字符串重复施加旧限制

### Requirement: Preserve archives and usable links without field citations
系统 SHALL 保存原文快照、规范正文、来源 URL、文档时间及版本，关联知识使用的文档。申请链接和官网链接 SHALL 保留明确用途；未知链接不得编造。结构化字段 MUST NOT 因无逐字引文、证据 ID、字符定位或原文字符串匹配而被拒绝。

#### Scenario: Valid structured facts have no quotation
- **WHEN** 提取结果包含有效金额、币种、适用关系和链接，但没有逐条证据且价格说明为空
- **THEN** 完成结构与业务校验后可继续生产，原文仍能按文档版本访问

### Requirement: Resolve identities and associations without legacy facts
来源 SHALL 通过来源绑定关联活动及期次，目录 SHALL 使用明确提取的项目/等级及现有归一化能力建立。方案、映射和价格 SHALL 有明确归属，阶段记录保留必要草稿与错误；它们不得成为独立于正式知识的第二套权威事实。

#### Scenario: Multiple activities share one article analysis
- **WHEN** 一篇文章的一次分析发现两个不同活动
- **THEN** 保留一次分析记录，建立各活动的绑定和知识版本，不依赖分析记录唯一约束、不生成旧文章机会记录

#### Scenario: A price cannot be assigned to every mapping
- **WHEN** 同一活动有不同收费方案或某个价格的适用范围不明确
- **THEN** 保留明确的方案关联与未知状态，不把最低价或某目标费用套给所有映射

### Requirement: Publish consistent versions with recoverable failures
系统 SHALL 在必要简报及图数据检查完成后以短事务复核输入与基础版本，再发布并切换当前版本；失败不得污染旧发布版本。去重、阶段缓存和并发冲突 SHALL 使用当前文档/契约/知识版本。

#### Scenario: Source changes while the model runs
- **WHEN** 模型处理期间源文档或基础知识版本发生变化
- **THEN** 过期结果不覆盖当前版本，记录可重试原因

#### Scenario: Generation fails before publication
- **WHEN** 提取、结构校验、简报或图投影准备失败
- **THEN** 保存明确失败阶段，当前有效发布版本保持不变，采集成功不被报告为知识更新成功

### Requirement: Limit schema coupling to storage interfaces
共享代码 SHALL 提供稳定知识契约和必要存取边界；AIWorkflow 不依赖 Agent 状态，Agent 不导入生产调度或发布实现。不为适配新库增加通用业务控制器或永久旧事实转换层。

#### Scenario: Agent is disabled
- **WHEN** Agent 模型和运行循环均未启动
- **THEN** AIWorkflow 仍可处理、发布，知识页面仍可读取产物
