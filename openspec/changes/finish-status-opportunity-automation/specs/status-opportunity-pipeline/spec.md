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

### Requirement: Gmail 必须展开有用的 StatusMatch 活动链接
Gmail 适配器 MUST 检查邮件 HTML 中所有文字链接、按钮和仅图片可点击锚点，并 MAY 从纯文本正文补充 URL。系统 MUST 在本地递归解开受支持的 StatusMatch 邮件跟踪包装，MUST NOT 访问带收件人或点击标识的跟踪中转地址。系统 MUST 排除无关链接，只将主机为单一项目专属 `*.statusmatch.com` 子域的 HTTPS 链接视为 StatusMatch 活动；`www`、邮件跟踪、社交、退订、条款和宣传入口不属于活动链接。系统 MUST 按规范化项目主机去重，并为每个项目分别读取活动首页和同域 `/faq`。

#### Scenario: 图片按钮是唯一活动入口
- **WHEN** 邮件正文没有可见文字 URL，只有一个 `<a href>` 包裹带 alt 文字的图片按钮
- **THEN** 系统仍发现并本地解包该链接，规范化到项目专属 StatusMatch 主机

#### Scenario: 一封邮件包含无关和重复链接
- **WHEN** 同一项目活动以正文、按钮和图片重复出现，同时邮件还包含社交、退订、隐私和课程宣传链接
- **THEN** 系统只为该项目建立一组活动首页和 `/faq` 材料，不请求或处理无关链接

#### Scenario: 跟踪链接嵌套活动链接
- **WHEN** StatusMatch 邮件跟踪载荷先指向通用点击页，再由查询参数指向项目活动页
- **THEN** 系统在本地递归得到最终项目 URL、丢弃私人跟踪参数，并只请求最终项目首页与 `/faq`

### Requirement: StatusMatch 详细页必须作为独立增量事实材料
每个去重项目主机的活动首页与 `/faq` SHALL 使用稳定的来源条目和规范 URL 独立保存。邮件正文 SHALL 保留用于来源审计和活动发现，但 MUST 确定性标为非业务材料，不得创建活动提示或进入事件证据、事实、简报及 `source_links`；公开页面 SHALL 作为资格、映射、价格、申请窗口、有效期、入口和注意事项的详细事实材料，且不得套用仅用于邮件正文的链接清洗规则。系统 MUST 在邮件来源的每日采集中重新检查已发现页面；内容未变化且清洗解析版本相同时不得创建新文档版本，正文变化或清洗解析版本升级时必须保留旧版本并创建新版本。自动积压只选择每个来源条目的最新文档版本，受控初始化只处理本次当前发现集合。首页与 `/faq` 共享项目主机 SHALL 成为防串线的强关系信号，但页面路径本身不得把同一活动拆开。

#### Scenario: FAQ 包含比首页更详细的映射规则
- **WHEN** 活动首页只有概述而 `/faq` 列出多项资格等级、目标等级、价格或有效期
- **THEN** 系统使用两页完整正文提取和总结关键信息，并把各项事实绑定到对应页面证据

#### Scenario: FAQ 映射表位于历史地区费用表之后
- **WHEN** `/faq` 的 `Recently ended offers` 下先出现历史国家/地区与申请费表，之后另有航司或酒店原会籍到目标会籍的对应表
- **THEN** 系统不把历史地区费用写入当前活动事实，但逐行逐目标等级结构化后面的对应表，保留可用、受条件限制和不可用单元及对应 FAQ 证据

#### Scenario: 公开页面内容没有变化
- **WHEN** 次日采集重新读取同一活动首页和 `/faq` 且原始内容哈希不变
- **THEN** 系统复用已有来源条目和文档版本，不重复生成业务事件或简报

#### Scenario: 邮件正文包含活动概述
- **WHEN** 邮件正文自身描述活动名称、申请提示或通用条款
- **THEN** 这些文字仍只用于链接发现和审计，不得成为事实证据或简报来源；系统只引用展开后的公开页面

#### Scenario: 删除干扰邮件后重试初始化
- **WHEN** 前一次 Gmail 初始化失败后用户删除了注册或验证干扰邮件并再次运行
- **THEN** 系统重新查询当前邮箱并只处理本次发现的邮件及去重公开页面，不复用前一次成功采集清单或继续处理已删除邮件的历史待办

## MODIFIED Requirements

### Requirement: 来源注册兼容与当前运行范围必须分离
系统 MUST 在统一来源注册表中保留 Frequent Flyer Bonuses 博客、AwardWallet Elite Status、StatusMatch/GetStatus 邮件、LoyaltyLobby、Frequent Miler Elite Status 和很旅行的适配器、稳定 `source_id`、完整 URL、正文策略、访问限制及历史兼容。当前产品 MUST 只启用 `loyaltylobby_feed` 通用文章链路和 `status_services_mail` 专用项目链路；其他四个公开来源 MUST 保持 `enabled=false`、`automatic_scheduling=false`，不得进入当前通用处理。每个来源适配器 MUST 只负责发现和获取材料，并输出统一的来源条目与文档契约，不得直接创建业务事件。StatusMatcher 与 Frequent Flyer Bonuses 会籍汇总列表 MUST 不存在于正式注册表、CLI 可选来源或自动调度范围。

#### Scenario: 注册表成为唯一来源配置输入
- **WHEN** 系统初始化会籍来源配置
- **THEN** 它导入六条兼容来源记录及其入口和策略，其中只有 LoyaltyLobby 与 StatusMatch/GetStatus Gmail 启用，StatusMatch 与 GetStatus 邮件共用 `status_services_mail`，且不导入 StatusMatcher 或 FFB 会籍汇总列表

#### Scenario: 自动运行选择当前来源
- **WHEN** 每日单轮选择到期来源和待处理文档
- **THEN** 通用处理只选择 LoyaltyLobby，StatusMatch/GetStatus Gmail 只进入专用链路，其他四个公开来源的历史积压不被读取或计数

#### Scenario: 关闭来源仍可保留适配器契约
- **WHEN** FFB Feed、AwardWallet、Frequent Miler 或很旅行的 Feed、栏目页或目录页只提供文章入口
- **THEN** 对应适配器发现稳定条目标识和正文地址，并按该来源配置获取正文或Feed内全文

#### Scenario: 邮件保持只读和幂等
- **WHEN** 邮件适配器读取 StatusMatch 或 GetStatus 的允许邮件
- **THEN** 系统以邮件消息ID建立来源条目，不修改、移动或删除用户邮件

#### Scenario: Gmail发现范围受到双重限制
- **WHEN** 邮件适配器从 `kirikoomiku@gmail.com` 发现消息
- **THEN** 它只使用 `gmail.readonly` 权限读取同时具有 `statusmatch` 标签且发送至 `kirikoomiku+statusmatch@gmail.com` 的消息，不读取其他邮件或更改现有过滤器

#### Scenario: 专用别名替代发件人白名单
- **WHEN** 一封邮件同时具有 `statusmatch` 标签且发送至 `kirikoomiku+statusmatch@gmail.com`
- **THEN** 系统将其作为 `status_services_mail` 链接发现材料，不要求真实发件人白名单；可识别时只额外记录 StatusMatch 或 GetStatus 品牌归属，邮件本身不进入业务分析

#### Scenario: Feed内有正文时不重复抓文章页
- **WHEN** LoyaltyLobby、Frequent Miler 或很旅行的 Feed 条目已提供允许使用的正文
- **THEN** 适配器直接使用Feed正文，并遵守注册表中禁止或无需继续请求文章页的策略

### Requirement: 当前通用文章保持文章级独立，StatusMatch 关系只在专用链路内处理
LoyaltyLobby 新文档 MUST 使用文章级 V2，每个文档版本产生独立、可审计的文章分析和零个或多个 `ArticleOpportunity`，MUST NOT 召回 `StatusEvent` 候选、调用通用关系 AI、返回 `SAME_EVENT / UPDATE_OF` 或跨文章协调事实。旧 V1 事件、关系、证据和 FactSet MUST 保留用于历史审计和回滚，但 MUST NOT 接收新的 LoyaltyLobby 自动处理结果。精确包含项目专属 `*.statusmatch.com` 链接的 LoyaltyLobby 文章 MUST 路由到 StatusMatch 第三方补充链路；StatusMatch Gmail 发现的同域首页与 `/faq` MAY 在专用项目链路中按项目主机组成同一官方项目，但邮件本身不得成为业务材料。

#### Scenario: 两篇 LoyaltyLobby 文章报道同一活动
- **WHEN** 两篇新文章描述同一会籍机会
- **THEN** 系统分别保存文章级机会，不调用关系 AI 或自动合并为共享 `StatusEvent`，以后如需跨文章分组必须另建只读投影

#### Scenario: LoyaltyLobby 文章精确链接 StatusMatch 项目
- **WHEN** 文章包含具体项目专属 `*.statusmatch.com` 链接
- **THEN** 系统在通用标题筛选前将文章路由到 StatusMatch 第三方补充链路，不生成通用文章机会，也不修改官方 FactSet

#### Scenario: 同一邮件发现同域首页和 FAQ
- **WHEN** StatusMatch 邮件链接已规范化到项目专属子域且系统取得同域首页与 `/faq`
- **THEN** 邮件只完成发现；专用项目链路使用两个公开页面共有的项目主机组成同一官方项目，不将邮件加入业务证据

#### Scenario: 数据库已有旧 V1 事件
- **WHEN** 升级后的数据库保留旧的跨文章事件、关系、事实与简报
- **THEN** 这些数据继续可审计和回滚读取，但当前 LoyaltyLobby 自动处理不追加新证据或修改其关系
