## ADDED Requirements

### Requirement: 单次补充分析同时提取候选匹配关系
StatusMatch 第三方文章处理 SHALL 在现有一次补充 AI 调用中同时返回补充亮点和显式候选会籍匹配声明；增加候选声明不得增加新的模型阶段或重新生成官方简报。

#### Scenario: 文章含补充亮点和明确匹配关系
- **WHEN** 已路由的第三方文章同时包含官方简报之外的有效亮点和明确的原项目/原等级到目标等级陈述
- **THEN** 一次结构化输出同时包含 `highlights` 和 `candidate_status_mappings`
- **AND** 总模型调用数仍为一次，有限纠错重试除外

#### Scenario: 文章没有可用匹配关系
- **WHEN** 第三方文章只有评论、权益分析或没有完整直接映射
- **THEN** `candidate_status_mappings` 为空
- **AND** 亮点处理仍可独立成功

### Requirement: 候选关系复用统一核心语义
每个第三方候选关系 SHALL 复用与官方 StatusMatch 映射一致的核心字段和校验规则，包括 `source_program`、`source_tiers`、`target_tier`、`availability`、`conditions`、`evidence`、`conflict` 和 `conflict_note`；目标项目 SHALL 从精确路由绑定的官方事件身份解析。

#### Scenario: 可用直接映射
- **WHEN** 文章明确说明一个或多个原等级可以申请绑定项目的某个目标等级
- **THEN** 系统生成满足官方映射字段约束的候选关系
- **AND** 每个非不可用关系至少包含一个原等级
- **AND** 条件关系包含明确条件

#### Scenario: 不可用关系
- **WHEN** 文章明确说明某原项目当前不能匹配到目标项目
- **THEN** 候选关系使用 `UNAVAILABLE`
- **AND** 不列出可用的 `source_tiers`

### Requirement: 第三方来源包装与精确证据
候选关系 SHALL 通过独立来源包装保存第三方身份、路由、文章文档、对照官方 FactSet 和审核状态；每个候选关系 SHALL 包含逐字存在于第三方文章的短引用，并不得把官方 HOME、FAQ、FactSet 或 Brief 伪装为文章证据。

#### Scenario: 保存第三方候选声明
- **WHEN** 候选关系通过结构与引用校验
- **THEN** 系统保存 `source_type=THIRD_PARTY`、文章 DocumentVersion、route ID、project host、目标 event ID、对照 FactSet ID 和验证状态
- **AND** 标准证据引用指向第三方文章 URL 与 DocumentVersion

#### Scenario: 引用不在文章中
- **WHEN** 候选关系的引用不能逐字定位于第三方正文
- **THEN** 该候选关系不得成功持久化
- **AND** 系统在有限纠错重试后记录失败诊断

### Requirement: 只接受直接声明而不发明多跳边
候选提取 SHALL 只保存文章明确陈述的直接原会籍到目标会籍映射；由两条或更多关系推导出的可达结果不得被保存为新的直接候选关系。

#### Scenario: 文章明确陈述两条连续关系
- **WHEN** 文章分别明确陈述 `A → B` 和 `B → C`
- **THEN** 系统最多保存这两条直接声明
- **AND** 不得保存文章未直接陈述的 `A → C`

#### Scenario: 文章只表达策略性推测
- **WHEN** 文章说某会籍“可能可以用来继续匹配”但没有明确原项目、原等级和目标等级
- **THEN** 系统不得创建候选匹配关系
- **AND** 该内容只能在符合亮点规则时作为编辑观察保存

### Requirement: 候选关系与官方事实确定性对照
系统 SHALL 以绑定项目的当前官方 `status_mappings` 对第三方候选关系进行确定性比较，并把结果区分为 `CORROBORATED`、`CANDIDATE`、`CONFLICTING` 或 `REJECTED`；人工确认后可转为 `APPROVED`。

#### Scenario: 与官方映射一致
- **WHEN** 候选关系与当前官方关系的原项目、原等级、目标等级、可用性和条件一致
- **THEN** 状态为 `CORROBORATED`
- **AND** 不创建重复图边或修改官方 FactSet

#### Scenario: 官网当前没有该关系
- **WHEN** 候选关系结构完整但当前官方 FactSet 没有等价关系
- **THEN** 状态为 `CANDIDATE`
- **AND** 关系保持第三方候选身份等待后续确认

#### Scenario: 与官网冲突
- **WHEN** 候选关系在相同作用域内与当前官方关系的目标等级、可用性或条件互斥
- **THEN** 状态为 `CONFLICTING`
- **AND** 系统保存双方来源供复核

#### Scenario: 非直接或无效关系
- **WHEN** 候选关系属于多跳推导、缺少必要字段或不能通过证据校验
- **THEN** 状态为 `REJECTED` 或不予持久化

### Requirement: 官方 FactSet 与匹配图权威边界
第三方候选关系 SHALL 与官方 StatusMatch FactSet 分开持久化；官方图默认只从 ACTIVE 项目的当前官方 FactSet 构建，第三方关系只有在符合明确图策略时才可参与展示或遍历。

#### Scenario: 候选关系生成后官方项目更新
- **WHEN** 第三方候选关系已经保存且官方 HOME 或 FAQ 产生新 FactSet
- **THEN** 官方 FactSet 不包含第三方关系
- **AND** 候选关系继续保留原文章和原对照 FactSet 的审计信息
- **AND** 系统可以对新官方 FactSet 重新执行确定性状态比较

#### Scenario: 默认官方图查询
- **WHEN** 用户查询默认 StatusMatch 匹配图
- **THEN** `CANDIDATE`、`CONFLICTING` 和未经批准的第三方声明不得生成主图可遍历边

#### Scenario: 候选图层查询
- **WHEN** 调用方显式请求候选图层
- **THEN** 系统可以展示 `CANDIDATE` 和 `CONFLICTING` 声明
- **AND** 必须清楚返回第三方来源、验证状态、文章证据和非官方标识

#### Scenario: 人工批准候选关系
- **WHEN** 第三方候选关系经显式人工操作转为 `APPROVED`
- **THEN** 图服务可以按批准关系策略生成带第三方来源的可遍历声明
- **AND** 官方 FactSet 仍不得被修改

### Requirement: 共享领域模型而非工作流耦合
统一的会籍映射核心和来源包装 SHALL 位于与具体来源及 StatusMatch 工作流无关的领域模块；通用文章链路、StatusMatch 项目链路和图服务 SHALL 通过各自适配器消费该领域模型。

#### Scenario: 检查模块依赖
- **WHEN** 检查会籍映射相关实现
- **THEN** 核心映射和来源包装不包含 LoyaltyLobby 专属字段或 StatusMatch Workflow 调用
- **AND** 来源特有的 route ID、project host 和文章文档信息只存在于 provenance 包装或适配器中

