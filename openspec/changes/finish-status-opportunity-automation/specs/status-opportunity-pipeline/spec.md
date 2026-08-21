## ADDED Requirements

### Requirement: 活动身份只增加最小申请窗口
系统 SHALL 继续使用 `program`、`opportunity_type`、`target_status`、`summary` 和关联完整材料判断现实活动身份，并只增加可空的申请开始和截止窗口作为关系判断信息。系统 SHALL NOT 在本变更中增加合作方、地区、入口指纹或活动系列 ID 等事件身份字段。

#### Scenario: 同品牌同期存在不同活动
- **WHEN** 同一忠诚度项目在重叠窗口内同时存在企业专场和普通匹配
- **THEN** 系统结合现有事件语义和完整材料把它们保持为不同事件，不因窗口重叠自动合并

#### Scenario: 新材料没有日期
- **WHEN** 新材料没有明确申请窗口但其他语义明确指向已有活动
- **THEN** 系统仍可将它关联到已有事件，不因日期缺失强制拆分

## MODIFIED Requirements

### Requirement: 七组精选来源通过统一适配契约接入
系统 MUST 支持 Frequent Flyer Bonuses 博客、Frequent Flyer Bonuses 会籍汇总页、AwardWallet Elite Status、StatusMatch/GetStatus 邮件、LoyaltyLobby、Frequent Miler Elite Status 和很旅行七组来源。实施使用的稳定 `source_id`、完整 URL、正文策略、访问限制和默认状态 MUST 来自同一来源注册表，不得在业务模块另行猜测或散落配置。每个来源适配器 MUST 只负责发现和获取材料，并输出统一的来源条目与文档契约，不得直接创建业务事件。StatusMatcher MUST 不存在于正式注册表、CLI可选来源或自动调度范围。

#### Scenario: 注册表成为唯一来源配置输入
- **WHEN** 系统初始化会籍来源配置
- **THEN** 它导入七条来源记录及其入口和策略，其中 StatusMatch 与 GetStatus 邮件共用 `status_services_mail`，且不导入 StatusMatcher

#### Scenario: 目录或Feed条目继续获取正文
- **WHEN** Feed、栏目页或目录页只提供文章入口
- **THEN** 对应适配器发现稳定条目标识和正文地址，并按该来源配置获取正文或Feed内全文

#### Scenario: 静态汇总记录成为独立材料
- **WHEN** Frequent Flyer Bonuses 会籍汇总页包含多个顶层活动记录
- **THEN** 适配器为每个顶层记录产生稳定指纹，使单条变化可以独立处理

#### Scenario: 邮件保持只读和幂等
- **WHEN** 邮件适配器读取 StatusMatch 或 GetStatus 的允许邮件
- **THEN** 系统以邮件消息ID建立来源条目，不修改、移动或删除用户邮件

#### Scenario: Gmail发现范围受到双重限制
- **WHEN** 邮件适配器从 `kirikoomiku@gmail.com` 发现消息
- **THEN** 它只使用 `gmail.readonly` 权限读取同时具有 `statusmatch` 标签且发送至 `kirikoomiku+statusmatch@gmail.com` 的消息，不读取其他邮件或更改现有过滤器

#### Scenario: 专用别名替代发件人白名单
- **WHEN** 一封邮件同时具有 `statusmatch` 标签且发送至 `kirikoomiku+statusmatch@gmail.com`
- **THEN** 系统将其作为 `status_services_mail` 来源材料继续处理，不要求真实发件人白名单；可识别时只额外记录 StatusMatch 或 GetStatus 品牌归属

#### Scenario: Feed内有正文时不重复抓文章页
- **WHEN** LoyaltyLobby、Frequent Miler 或很旅行的 Feed 条目已提供允许使用的正文
- **THEN** 适配器直接使用Feed正文，并遵守注册表中禁止或无需继续请求文章页的策略

### Requirement: 跨材料语义去重形成现实事件
系统 MUST 将来源内容重复与现实事件重复作为两个不同问题处理。候选召回 MUST 使用现有事件语义和可用申请窗口缩小候选范围，`EventRelationshipAnalyzer` MUST 返回 `SAME_EVENT`、`UPDATE_OF`、`DIFFERENT_EVENT` 或 `UNCERTAIN`，并由确定性聚合器更新事件关系。申请窗口 MUST NOT 作为唯一事件键，候选召回 MUST 不依赖向量数据库。

#### Scenario: 多来源报道聚合到同一事件
- **WHEN** 两篇不同来源的材料描述同一会籍获取活动且窗口相同、重叠或一方未知
- **THEN** 系统将两份材料关联到同一个 `StatusEvent`，并各自保留来源证据

#### Scenario: 截止时间延期形成事件修订
- **WHEN** 新材料明确说明已有活动延长截止时间
- **THEN** 系统将它标为 `UPDATE_OF`、关联同一事件并保留旧版本

#### Scenario: 同品牌出现新的非重叠活动期次
- **WHEN** 新材料描述已结束活动之后的新申请窗口且没有明确延期语义
- **THEN** 系统返回 `DIFFERENT_EVENT` 并创建新事件，旧事件保持独立

#### Scenario: 同品牌同期不同活动保持分离
- **WHEN** 同一项目在重叠窗口内存在不同企业专场、地区专场或不同获取机制
- **THEN** 系统根据现有语义和完整材料把它们识别为不同事件

#### Scenario: 无法确定关系时不自动误合并
- **WHEN** 活动语义和窗口仍不足以确认关系
- **THEN** 系统返回 `UNCERTAIN`、建立人工复核项并在复核前保持材料和事件分离

#### Scenario: 新证据刷新候选召回文本
- **WHEN** 新材料被关联到已有事件并补充当前活动描述
- **THEN** 系统刷新事件当前摘要或搜索文本，使后续召回不只依赖首篇材料
