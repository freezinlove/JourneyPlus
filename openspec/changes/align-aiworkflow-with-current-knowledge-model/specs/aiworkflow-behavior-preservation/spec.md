## ADDED Requirements

### Requirement: Preserve the existing production baseline
实施 MUST 以现有三条生产分支为基线，记录阶段职责、顺序、分支、输入输出、模型调用、失败恢复、复用和消费者的改前改后对照。存储适配不得擅自删除或合并生产环节；业务行为变化 MUST 先与用户讨论。

#### Scenario: A storage change touches a business decision
- **WHEN** 某个旧 ORM 函数同时负责价格策略和落库
- **THEN** 实施分别识别业务与存储职责，保留价格策略；不能因旧表退出而整段删除

### Requirement: Preserve official extraction channels
官方链 SHALL 保留 HOME/FAQ/TERMS 分工、确定性表格解析、模型补充、合并、冲突与关闭判断的既有能力，并直接产出统一草稿。

#### Scenario: Official tables and narrative both contribute
- **WHEN** FAQ/TERMS 含完整映射和价格表，正文还包含补充条件
- **THEN** 确定性解析和原模型补充共同生成方案、映射和价格，不让模型重新手抄已解析全表，不先写旧事实表

### Requirement: Preserve ordinary article stages
普通文章链 SHALL 保留批量标题筛选、筛选失败放行、正文一次提取多个活动、逐活动简报及各阶段复用和重试；关联 StatusMatch 的文章仍按原路由排除出普通匹配边生产。

#### Scenario: One article contains several opportunities
- **WHEN** 一篇放行文章包含多个活动
- **THEN** 通过一次原正文提取产生多个活动草稿，各自生成简报，不为每个活动新增全文提取

#### Scenario: Brief generation fails
- **WHEN** 正文提取已成功但其中一份简报失败
- **THEN** 保留成功提取结果，重试只执行需要的简报阶段

### Requirement: Preserve model invocation and resource semantics
正常生产路径 SHALL 保持现有阶段调用安排、缓存复用和重试上限，不因字段映射、目录身份、数据库写入或图生成而默认新增模型调用。HTTP 与模型调用 SHALL 在数据库事务外进行。调用对照 MUST 区分正常调用、缓存命中和重试。

#### Scenario: Schema alignment does not add another extraction
- **WHEN** 官方或文章已完成原有提取步骤
- **THEN** 程序装配并存储新结构，不再执行旧记录到统一知识的第二轮模型提取

#### Scenario: Cached input is unchanged
- **WHEN** 文档、契约、提示及相关配置版本与有效缓存一致
- **THEN** 复用阶段结果，计数记录显示没有重复模型调用

### Requirement: Preserve source and lifecycle policies
改造 SHALL 保留既有来源范围、增量更新、关闭检测、文章可见期和明确维护行为，不将初始化的一次性清理改为永久黑名单，不自动开启买分或其他历史链路。

#### Scenario: Official home confirms closure
- **WHEN** 现有关闭检测确认当前官方项目关闭
- **THEN** 依原政策处理监控并在新模型记录关闭，保留历史知识和文档，不依赖旧事件表
