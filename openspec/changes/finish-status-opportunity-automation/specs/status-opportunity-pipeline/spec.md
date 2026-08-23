## ADDED Requirements

### Requirement: 活动身份只保留最小语义并增加最小申请窗口
系统 SHALL 删除 `opportunity_type`，只使用 `program`、`target_status`、`summary`、来源提供的权威项目名和关联完整材料判断现实活动身份，并只增加可空的申请开始和截止窗口作为关系判断信息。系统 SHALL NOT 在本变更中增加合作方、地区、入口指纹或活动系列 ID 等事件身份字段。

#### Scenario: 同品牌同期存在不同活动
- **WHEN** 同一忠诚度项目在重叠窗口内同时存在企业专场和普通匹配
- **THEN** 系统结合现有事件语义和完整材料把它们保持为不同事件，不因窗口重叠自动合并

#### Scenario: 新材料没有日期
- **WHEN** 新材料没有明确申请窗口但其他语义明确指向已有活动
- **THEN** 系统仍可将它关联到已有事件，不因日期缺失强制拆分

#### Scenario: 机会机制措辞不同
- **WHEN** 两篇材料分别把同一现实活动描述为 status match、paid status 或 fast track
- **THEN** 系统不创建或比较机会类型字段，而使用项目、活动语义和完整材料判断关系

### Requirement: 活动提示必须按现实活动粒度输出
分类器 MUST 把同一现实活动的多个目标等级、价格档、资格映射或双向合作路径输出为一个活动提示，并 MUST 忽略主体活动中顺带推荐的一句话替代链接。不同目标忠诚度项目且各有独立行动入口的机会 MUST 拆分，即使一个会籍是另一个活动的资格来源。限时奖励精英定级房晚或定级积分的促销 SHALL 属于会籍机会。旅行预订、旅行顾问或旅行会员平台通过具体活动直接授予或升级到明确命名的持续精英等级时 SHALL 属于会籍机会；普通奖励积分、房券或折扣券促销以及只授予普通会员资格、券、折扣或权益包而不授予明确精英等级或定级进度的付费会员促销 SHALL 不属于会籍机会。

#### Scenario: 同一付费匹配具有多个档位
- **WHEN** GHA 或 Radisson 的同一匹配活动列出多个目标等级或价格
- **THEN** 文档输出一个活动提示而不是按档位拆分

#### Scenario: 合作包含双向会籍路径
- **WHEN** Marriott 与 JAL 的同一合作活动允许双方会员按不同方向获得会籍
- **THEN** 文档输出一个合作活动提示

#### Scenario: 两项 IHG 精英房晚促销
- **WHEN** 两篇材料分别描述上限、适用对象和窗口不同的限时双倍精英房晚活动
- **THEN** 两篇均标为 `STATUS_OPPORTUNITY`，并归入两个独立事件

#### Scenario: 主体活动顺带提及替代选择
- **WHEN** Flying Blue 主体报道只在末尾顺带推荐 Vietnam Airlines
- **THEN** 系统不为该顺带提及增加活动提示

#### Scenario: 雅高混合文章包含等级房晚和房券
- **WHEN** 文章同时描述赠送5个等级房晚、赠送五折房券和 Kenya Airways 会籍匹配
- **THEN** 系统输出雅高等级房晚与 Kenya Airways 两个活动提示，不为五折房券输出提示

#### Scenario: 马航文章包含独立的 Garuda 付费金卡
- **WHEN** 文章先描述 Malaysia Airlines Enrich 匹配，再通过独立官方入口描述 Garuda Gold Privilege 付费金卡
- **THEN** 系统为两个目标忠诚度项目各输出一个活动提示，不把 Garuda 仅视为马航资格背景

#### Scenario: 低价值混合攻略不纳入本期
- **WHEN** iPrefer 混合游记以个人兑换和经验分享为主，仅顺带描述邮件匹配经历
- **THEN** 本期金标与分类策略将该文档标为 `NONE`

#### Scenario: 个人邮件匹配数据点没有公开活动依据
- **WHEN** 材料只有个人通过客服邮箱申请成功的经历和第三方数据点，没有官方公开活动页，也没有可确认的群体资格、条款或公告
- **THEN** 系统只把它视为个案攻略并标为 `NONE`，并使用确定性公开性守卫覆盖不稳定的模型正判，不得由个人成功结果推断存在公开会籍活动

#### Scenario: 旅行会员平台通过活动直升精英等级
- **WHEN** 旅行预订、旅行顾问或旅行会员平台提供完成一次入住后直接升级到明确命名的金卡等级活动
- **THEN** 系统将该活动标为 `STATUS_OPPORTUNITY`，不因运营方不是航司、酒店或租车公司而排除

#### Scenario: 普通付费会员产品只赠送券
- **WHEN** 用户购买名称含会籍、Plus、Pass、Club 或 Card 的普通会员产品，结果只有会员资格、餐饮券、折扣或权益包，没有明确精英等级或定级进度
- **THEN** 系统将该促销标为 `NONE`

### Requirement: FFB 顶层公司名必须作为权威项目名
对于 Frequent Flyer Bonuses 会籍汇总页，系统 MUST 把每个顶层记录左侧的公司或项目名称作为该材料的权威 `program`，并保留右侧正文原文。权威项目名 MUST 约束分类输出并参与候选召回，但 MUST NOT 作为自动合并键；同一公司下的不同时期或不同活动记录仍由关系判断拆分。

#### Scenario: KM 正文包含来源笔误
- **WHEN** FFB 顶层记录左侧为 `KM Malta Airlines KM Rewards`、行动链接指向 KM，但右侧正文误写 Kenya Airways
- **THEN** 系统保留原始正文，活动提示使用 KM 权威项目名，并在候选层排除项目名不兼容的 Kenya 活动

#### Scenario: 同一公司存在多个顶层记录
- **WHEN** FFB 页面为 Air France KLM 或 Alaska Airlines 展示多个独立顶层记录
- **THEN** 系统分别处理每条材料，并继续根据完整活动语义判断合并或拆分

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
系统 MUST 将来源内容重复与现实事件重复作为两个不同问题处理。候选召回 MUST 使用项目名称包含关系、显著名称词重叠、运行时从材料提取的行动链接、现有事件语义和可用申请窗口缩小候选范围，并 MUST 排除已归档、生命周期为 `EXPIRED` 或可靠截止时间已过的事件。`EventRelationshipAnalyzer` MUST 对调用方传入的关闭事件执行相同防守性过滤，并返回 `SAME_EVENT`、`UPDATE_OF`、`DIFFERENT_EVENT` 或 `UNCERTAIN`，同时返回结构化布尔字段 `deadline_extension`；该字段只有在候选尚未超过原截止时间且未归档、正文明确说明截止时间延期且关系为 `UPDATE_OF` 时才可为 `true`。确定性聚合器据此更新事件关系。普通行动链接只作为临时召回信号，不得新增为事件身份字段；召回相似只代表候选资格，不得直接合并。相同的项目专属 `*.statusmatch.com` 子域同时与新提示及唯一候选的项目身份相符且不存在已知非重叠窗口时，MAY 作为确定性的 `SAME_EVENT` 强信号；路径、查询参数和地区入口差异本身不得强制拆分。同页其他活动的链接、不同项目子域、后续非重叠活动窗口或关闭的候选事件 MUST 阻止该强信号误合并。申请窗口 MUST NOT 作为唯一事件键，候选召回 MUST 不依赖向量数据库。

#### Scenario: 多来源报道聚合到同一事件
- **WHEN** 两篇不同来源的材料描述同一会籍获取活动且窗口相同、重叠或一方未知
- **THEN** 系统将两份材料关联到同一个 `StatusEvent`，并各自保留来源证据

#### Scenario: 截止时间到达前宣布延期形成事件修订
- **WHEN** 原活动尚未超过截止时间且未归档，新材料明确说明已有活动延长截止时间
- **THEN** 系统将它标为 `UPDATE_OF`、设置 `deadline_extension=true`、关联同一事件并保留旧版本

#### Scenario: 截止时间到达后才出现延期材料
- **WHEN** 原活动已经超过可靠截止时间或已经归档，后来材料写明 OFFER EXTENDED、重开或新的截止时间
- **THEN** 旧活动不得进入候选，系统返回 `DIFFERENT_EVENT` 并创建新事件，旧事件保持归档

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

#### Scenario: 项目全称与简称不同
- **WHEN** 材料使用 Kenya Airways 与 Kenya Airways Asante Rewards、Alaska Airlines 与 Alaska Airlines Atmos Rewards 或 Flying Blue 与 Air France KLM Flying Blue 等不同名称
- **THEN** 候选召回把可能的同项目事件交给关系模型，但不因名称包含或词重叠自动合并

#### Scenario: 中英文项目名没有词面重叠
- **WHEN** 很旅行使用 `马来西亚航空`、FFB 使用 `Malaysia Airlines Enrich`，但两份材料都包含 `enrich.statusmatch.com` 行动入口
- **THEN** 候选召回不得被 FFB 权威英文名过滤掉，关系层使用项目专属子域将两份材料聚合，数据库不增加行动链接身份字段

#### Scenario: 同一项目专属子域使用不同路径
- **WHEN** Flying Blue 英国入口使用 `flyingblue.statusmatch.com/ba/`，通用入口使用同一子域根路径
- **THEN** 关系层把子域作为强关系信号并聚合为同一活动，不因路径、查询参数或目标地区不同拆分

#### Scenario: 多活动文档不得串用子域
- **WHEN** 一篇文档同时描述 Malaysia Airlines Enrich 与 Garuda Gold Privilege，只有前者使用 `enrich.statusmatch.com`
- **THEN** 该子域只能关联 Enrich 提示，不得把 Garuda 活动合并进 Enrich 事件

#### Scenario: 不同项目子域保持分离
- **WHEN** KM Rewards 使用 `kmrewards.statusmatch.com`，正文笔误提到的 Kenya Airways 使用 `kenya-airways.statusmatch.com`
- **THEN** 两者不得因同属 StatusMatch 平台或正文笔误而召回或合并

#### Scenario: 同一命名授予计划存在国家入口
- **WHEN** Best Western Service Rewards 对美国和加拿大军人分别提供注册入口但授予机制相同
- **THEN** 系统把两份材料聚合为同一现实活动，不仅因国家和注册链接不同而拆分
