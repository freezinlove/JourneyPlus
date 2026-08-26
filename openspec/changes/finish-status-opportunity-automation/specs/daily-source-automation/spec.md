## ADDED Requirements

### Requirement: 当前两条来源链路每天运行且关闭来源不得进入自动化
系统 MUST 只把 `loyaltylobby_feed` 作为当前通用公开来源，把 `status_services_mail` 作为 StatusMatch/GetStatus 专用来源，并为两者配置一天采集周期和自动选择。FFB 会籍 Feed、AwardWallet、Frequent Miler 和很旅行 SHALL 保留适配器、注册记录、原文及历史结果，但 MUST 保持 `enabled=false`、`automatic_scheduling=false`，不得进入当前通用处理。StatusMatcher 与 FFB 会籍汇总列表 MUST 不参与任何自动周期。

#### Scenario: 当前自动来源策略生效
- **WHEN** 系统播种来源并执行每日单轮
- **THEN** 只有 LoyaltyLobby 和 StatusMatch/GetStatus Gmail 具有一天周期并可被自动选择，前者进入通用文章 V2，后者只进入 StatusMatch 专用链路

#### Scenario: 数据库保留其他公开来源
- **WHEN** 数据库中已有 FFB Feed、AwardWallet、Frequent Miler 或很旅行的来源记录、原文或历史派生结果
- **THEN** 系统保留这些数据但不自动采集、不送入当前通用处理，也不把其积压计入当前自动化状态

### Requirement: 单轮自动化必须按北京时间自然日幂等且互斥
系统 MUST 提供可由外部定时任务调用的单轮命令，使用数据库租约防止并发执行，并以来源和 `Asia/Shanghai` 自然日建立幂等键。同一北京时间日期重复触发 MUST 复用已成功来源运行，且不得重复产生采集、文档、分析、事件或简报；失败来源 MAY 在当天安全重试。

#### Scenario: 同一北京时间日期重复调用
- **WHEN** 单轮命令在同一北京时间日期内被重复触发
- **THEN** 已成功来源运行被复用，失败或未运行来源可重试，且不会重复处理同一材料

#### Scenario: 上一轮仍在运行
- **WHEN** 新调用发现有效的自动化租约
- **THEN** 新调用安全退出并记录跳过原因

### Requirement: 当前两个来源必须从成功边界增量发现
系统 MUST 为 LoyaltyLobby 与 StatusMatch/GetStatus Gmail 持久化各自的发现边界，并且边界 MUST 只在不会遗漏本批材料的成功采集后推进。LoyaltyLobby 在没有持久化游标时 MUST 把 `Asia/Shanghai` 的 2026-08-24 全天视为已经完整入库，只分页返回该自然日之后的文章；首次成功后 MUST 使用最新连续处理的 Feed GUID 作为下一次停止边界，不得在每次运行中重新扫描到 2026-08-24。Gmail 在没有 History ID 或 History ID 过期时 MUST 对当前标签与专用别名执行 message ID 全量对账，正常运行 MUST 使用 Gmail History 增量读取新增邮件和后加标签邮件。内容哈希 MUST 继续提供最终版本幂等，但不得代替发现游标。

#### Scenario: LoyaltyLobby 首次升级追赶
- **WHEN** 数据库已有北京时间 2026-08-24 全天文章且尚无发现游标
- **THEN** 系统从最新 Feed 分页到该日期边界，只返回 2026-08-24 之后尚未扫描的文章，并在成功后保存连续处理位置

#### Scenario: LoyaltyLobby 后续增量运行
- **WHEN** LoyaltyLobby 已保存上次成功处理的 Feed GUID
- **THEN** 系统只扫描最新页到该 GUID，返回中间新增文章，且文章历史增长不会使扫描重新回到日期基线

#### Scenario: LoyaltyLobby 单轮上限小于新增数量
- **WHEN** 新增文章数量超过来源条目上限
- **THEN** 系统从旧到新处理新增文章，只推进到本轮实际成功处理的最新 GUID，下一轮继续剩余文章而不跳过

#### Scenario: Gmail History 正常增量
- **WHEN** 已保存有效 Gmail History ID
- **THEN** 系统只读取该 ID 之后新增或后加 `statusmatch` 标签的候选邮件，并在当前标签和专用别名复核通过后处理

#### Scenario: Gmail History 过期
- **WHEN** Gmail 拒绝已保存的 History ID
- **THEN** 系统执行当前 message ID 全量对账、跳过已有成功正文，并在整批成功后保存新的 History ID

#### Scenario: 增量批次失败或超过安全上限
- **WHEN** 来源发现、获取或非托管材料处理失败，或 Gmail 整批无法在来源条目上限内安全完成
- **THEN** 系统保留旧游标供重试，不得推进游标后静默丢失材料

### Requirement: 单轮自动化必须完成采集、处理和生命周期推进
一次自动化周期 MUST 顺序采集到期且启用的来源、处理本轮新增和既有待处理文档、推进适用的生命周期并输出运行摘要。LoyaltyLobby MUST 进入当前文章级 V2；StatusMatch/GetStatus Gmail MUST 只进入专用项目链路。文档处理和本轮积压 MUST 只统计本轮选中的当前来源；已移除、已停用或未选中的来源原文 MUST NOT 被本轮处理，也不得计入当前来源总积压。系统 MUST 为单轮来源条目、待处理文档和模型调用设置可配置上限。

#### Scenario: LoyaltyLobby 发现新文章
- **WHEN** LoyaltyLobby 产生新的文档版本
- **THEN** 同一周期在上限内完成标题筛选、正文理解、文章机会、证据化事实、简报和适用的生命周期更新，不调用通用关系或二次事实 AI

#### Scenario: 待处理数量超过上限
- **WHEN** 本轮积压超过配置上限
- **THEN** 系统处理上限内项目、保留剩余积压并在运行摘要中报告

#### Scenario: 数据库保留已停用来源原文
- **WHEN** 数据库中仍保留已关闭公开来源、已移除 FFB 汇总列表或 StatusMatcher 的原始文档
- **THEN** 单轮处理不读取这些文档，自动化状态也不把它们计入当前来源积压

#### Scenario: 仅显式运行一个正式来源
- **WHEN** 操作者定向运行一个正式来源且另一正式来源仍有历史积压
- **THEN** 本轮只处理并报告所选来源的文档，未选来源的积压保留到其自己的运行

### Requirement: 来源故障必须隔离并可观察
一个来源的发现、获取、授权或解析失败 MUST 不阻塞其他来源。系统 MUST 保存每个来源的最后成功时间、最近失败、连续失败次数、新文档数量和待处理数量，并在周期摘要中报告分析失败与 `NEEDS_REVIEW` 数量。

#### Scenario: Gmail授权失效
- **WHEN** Gmail访问令牌不能刷新
- **THEN** 邮件来源记录失败，LoyaltyLobby 继续采集和处理

#### Scenario: 单个Feed结构失效
- **WHEN** 一个Feed无法发现或解析正文
- **THEN** LoyaltyLobby 本轮失败被记录，StatusMatch 专用链路和适用的生命周期推进继续执行

### Requirement: Gmail真实联调必须保护私人内容
系统 MUST 使用运行当时全部同时符合标签和专用别名条件的 StatusMatch 邮件，在本地 PostgreSQL 验证发现、获取、清洗、入库、链接页读取、重复采集幂等和完整分析链路；2026-08-23 首次技术验证时为四封，用户删除注册/验证干扰邮件后的正式重建集合为两封，数量本身不是固定契约。系统 MUST 从 HTML 的文字、按钮和仅图片可点击锚点发现链接，在本地递归解开受支持的 StatusMatch 邮件跟踪包装，且 MUST NOT 请求带私人跟踪参数的中转地址。系统 MUST 排除社交、退订、条款、宣传课程等无关链接，只把去重后的项目专属 `*.statusmatch.com` 域名视为有用活动链接，并读取其首页和同域 `/faq`。邮件原文无论是否发现有用链接都 MUST 只作为发现与审计记录，不得进入事件、事实、简报或引用；完整业务分析只处理公开首页与 FAQ。真实邮件标题、正文、可识别跟踪参数和消息标识 MUST NOT 写入仓库夹具、金标或运行报告。

#### Scenario: 第二次采集当前合规邮件
- **WHEN** 已完成首次入库后再次运行邮件来源
- **THEN** 系统按 Gmail message ID 复用已有来源条目，不创建重复文档、事件或简报

#### Scenario: 同一项目链接以文字和图片重复出现
- **WHEN** 一封或多封邮件通过文字按钮与图片锚点重复指向同一项目专属 StatusMatch 子域
- **THEN** 系统只建立一个活动首页条目和一个 `/faq` 条目，并按公开页面内容变化增量创建文档版本

#### Scenario: 邮件链接使用私人跟踪包装
- **WHEN** 项目链接先经过 StatusMatch 邮件跟踪域且包装中包含收件人或点击参数
- **THEN** 系统在本地解包并只请求规范化后的项目活动页，不访问中转地址、不把私人参数写入公开页面材料或日志

#### Scenario: 尚无GetStatus真实邮件
- **WHEN** 邮箱中只有StatusMatch邮件
- **THEN** 当前真实联调可以完成，GetStatus案例留待收到邮件后补充且不阻塞自动化上线

### Requirement: 外部调度前必须完成 Gmail 详情页和 LoyaltyLobby 受控验证
系统 MUST 在安装或启用外部每日定时任务前，全量处理当前 Gmail 邮件发现的去重 StatusMatch 活动首页与 `/faq`，并使用受控真实 LoyaltyLobby 批次验证当前通用文章 V2。审核 MUST 覆盖标题筛选、专用/通用路由互斥、文档标签、文档内机会数量、事实与逐字证据、简报、生命周期、模型调用预算和第二次运行幂等。FFB Feed、AwardWallet、Frequent Miler 和很旅行 MUST NOT 成为当前初始化阶段门。

#### Scenario: Gmail 活动详情初始化
- **WHEN** 开始正式业务库初始化
- **THEN** 系统从当前合规邮件重新发现有用项目域，对去重后的活动首页和 `/faq` 全量处理，使用当前时效流水线生成业务事件、事实、简报和生命周期；失败重试使用新的采集身份并只计算本次发现文档的处理积压

#### Scenario: LoyaltyLobby 真实批次验证
- **WHEN** Gmail 活动详情初始化已通过审核
- **THEN** 系统使用独立运行身份处理受控真实 LoyaltyLobby 批次并完成人工原文审核；旧固定两日窗口 MAY 用于 LoyaltyLobby 历史回放，但不得自动扩展到已关闭来源，也不要求跑完全部历史窗口

#### Scenario: 当前批次发现错误或新边界
- **WHEN** 原文审核发现标题误筛、路由串线、分类、事实、证据、简报、生命周期或调用预算错误，来源正文异常或尚未约定的产品边界
- **THEN** 系统记录材料、结果、原因和建议选项并停止外部调度启用，直到用户决策、修复和回归验证完成

#### Scenario: 用户批准从原始材料重建派生数据
- **WHEN** 初始化审核失败且用户明确批准清理旧结果重新生成
- **THEN** 系统先创建并验证 PostgreSQL 备份，只删除可从现有原始文档重建的分析、事件、事实、简报、任务和初始化状态，保留来源、SourceItem、DocumentVersion、CollectionRun、Gmail OAuth 与原始正文，然后使用新版本规则重新处理

### Requirement: 自动化观察通过后才能开始下一主题
系统 MUST 在完整测试和严格 OpenSpec 校验通过、LoyaltyLobby 与 StatusMatch/GetStatus Gmail 各自真实采集成功、Gmail 详情页和受控真实 LoyaltyLobby 批次审核通过，且自动单轮连续观察至少三个北京时间自然日没有重复业务数据、未隔离故障、无证据输出或额外通用关系/事实 AI 调用后，才把会籍主题标记为可维护并开始下一个主题。

#### Scenario: 观察期出现重复业务记录
- **WHEN** 自动运行观察期间发现同一材料重复创建文章机会、StatusMatch 项目产物或简报
- **THEN** 会籍主题不得完成，必须修复并重新开始观察

#### Scenario: 观察期无阻塞问题
- **WHEN** 完成门槛全部满足
- **THEN** 会籍主题进入维护状态，项目可以开始买分或转分主题
