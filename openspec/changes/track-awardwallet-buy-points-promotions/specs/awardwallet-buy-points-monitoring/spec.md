## ADDED Requirements

### Requirement: 系统只监控唯一 AwardWallet 买分汇总页
系统 SHALL 注册一个启用且每日自动调度的固定单页来源，只发现并获取 `https://awardwallet.com/news/current-promotions-buy-points-miles/`。系统 MUST NOT 从该页面继续发现或抓取 Feed、相关文章、活动详情页或购买入口，也不得跟随正文链接验证活动。

#### Scenario: 每日发现固定页面
- **WHEN** 固定单页来源执行发现
- **THEN** 系统只返回一个具有稳定来源内身份和 canonical URL 的条目，并将其标记为每次发现均需重新获取

#### Scenario: 页面包含详情和购买链接
- **WHEN** 已获取页面正文包含 AwardWallet 详情链接、affiliate 跳转或外部购买链接
- **THEN** 系统仅把链接作为活动字段保存，不向这些链接发送请求

#### Scenario: 最终页面越界
- **WHEN** 固定 URL 的最终响应跳转到预期 AwardWallet 页面之外
- **THEN** 本次来源采集失败且不创建该响应的成功文档版本

### Requirement: 固定页面必须复用通用版本化采集能力
系统 SHALL 使用现有 `SourceItem` 和 `DocumentVersion` 保存固定页面身份、原始 HTML、规范化正文、观察时间、内容哈希和获取时间。系统 MUST 每次计划运行重新请求页面，但相同原始或规范化内容 MUST 复用已有 DocumentVersion；真实内容变化 MUST 创建新版本且不得覆盖历史版本。

#### Scenario: 页面内容没有变化
- **WHEN** 系统在两个运行周期获取到原始或规范化内容相同的页面
- **THEN** 第二次运行更新来源观察状态但不创建重复 DocumentVersion

#### Scenario: 页面内容发生变化
- **WHEN** 页面活动或其他保留正文发生物质变化并产生新的内容哈希
- **THEN** 系统创建新的 DocumentVersion，同时保留旧原文、规范化正文和抓取时间

#### Scenario: 原始 HTML 与结构化解析共存
- **WHEN** 页面成功入库
- **THEN** 系统保留完整原始 HTML 供 DOM 解析，并保存经过来源专属清理的可读正文供哈希和审计

### Requirement: 系统必须确定性解析完整主活动列表
系统 MUST 在不调用 AI 的情况下，从航空、酒店和其他交通三个主活动区块的非表头行创建买积分/里程活动。顶部推荐表 MUST NOT 单独产生活动；若该表存在，系统 SHALL 用它为唯一匹配的主活动补充 Top 推荐标记和购买价格。

#### Scenario: 解析三个主分区
- **WHEN** 页面包含结构完整的航空、酒店和其他交通活动区块
- **THEN** 系统按 `AIRLINE`、`HOTEL`、`OTHER` 分类提取全部主活动行，且活动总数等于三个分区行数之和

#### Scenario: 顶部推荐子集补充主活动
- **WHEN** 顶部表格中的一行通过规范化购买链接或项目名唯一匹配主活动
- **THEN** 系统在该主活动上保存 `top_pick=true` 和可用的购买价格，不创建重复活动

#### Scenario: 顶部表格不存在
- **WHEN** 三个主分区完整但页面没有顶部推荐表格
- **THEN** 系统仍可生成成功快照，所有顶部补充字段保持空并在解析摘要中记录非阻断诊断

#### Scenario: 解析过程不使用 AI
- **WHEN** 系统处理任意 AwardWallet 买分页面版本
- **THEN** 处理器只使用确定性 DOM、文本、URL、数值和日期规则，不调用 AIProvider 且不增加任何模型调用计数

### Requirement: 每条活动必须保存可审计的买分专属字段
系统 SHALL 为每条活动保存稳定 `offer_key`、分类、页面项目名、完整活动原文、可选活动类型与百分比、可选每分购买价格、可选截止日期、到账时间、详情链接、购买入口、Top 标记以及字段级原文 evidence。无法确定的可选字段 MUST 保持空，不得由常识、其他页面或 AI 补全。

#### Scenario: 活动包含完整数值和日期
- **WHEN** 页面行明确写出 bonus 或 discount 百分比、截止日期和 Top 表购买价格
- **THEN** 系统同时保存原文和确定性规范化值，并使各值能够回溯到当前 DocumentVersion 的页面证据

#### Scenario: 活动没有截止日期或购买价格
- **WHEN** 页面对应单元格为空且主活动其余必需字段完整
- **THEN** 系统保存活动，`deadline_date` 或 `purchase_rate_cents` 保持空且不生成推测值

#### Scenario: 活动包含限定性措辞
- **WHEN** 活动原文包含 `up to` 或其他限定性措辞
- **THEN** 系统完整保留该原文，规范化数值不得替代或弱化限定条件

#### Scenario: 相对链接规范化
- **WHEN** 活动详情或购买入口使用相对 href
- **THEN** 系统以唯一目标页面为基准保存绝对 URL，同时在 evidence 中保留可审计的原始 href

### Requirement: 结构化快照和活动历史必须不可变且幂等
系统 SHALL 为每个成功解析的 DocumentVersion 和解析器版本保存一个不可变买分快照，并为快照内每条活动保存一条不可变活动记录。`(document_version_id, parser_version)` 和 `(snapshot_id, offer_key)` MUST 唯一；相同输入重跑 MUST 复用现有结果，解析器升级 MUST 保留旧版本快照。

#### Scenario: 相同页面版本重复处理
- **WHEN** 相同 DocumentVersion 使用相同解析器版本再次处理
- **THEN** 系统复用已有快照和活动，不创建重复记录

#### Scenario: 新页面版本修改活动
- **WHEN** 一个项目的优惠、截止日期、链接或 Top 状态在新 DocumentVersion 中变化
- **THEN** 系统在新快照中保存新结构化值，旧快照及其活动保持不变

#### Scenario: 解析器版本升级
- **WHEN** 操作者使用新解析器版本重新处理既有 DocumentVersion
- **THEN** 系统可创建新解析器版本的快照，同时保留旧解析结果用于审计和回滚

### Requirement: 活动身份必须对普通字段变化保持稳定
系统 MUST 优先使用规范化详情 URL，其次使用规范化购买 URL，最后使用分类和规范化项目名生成 `offer_key`。截止日期、优惠百分比、活动文字、购买价格、到账时间和 Top 状态 MUST NOT 进入身份键。同一快照出现重复或歧义身份时 MUST 拒绝整份解析。

#### Scenario: 同一项目活动延期
- **WHEN** 新快照中的同一详情链接仅改变截止日期或优惠文字
- **THEN** 前后记录具有相同 `offer_key`，变化读取将其识别为 `CHANGED` 而不是无关的新活动

#### Scenario: 页面出现重复身份
- **WHEN** 两个主活动行生成相同 `offer_key`
- **THEN** 系统判定页面结构或建模边界存在歧义，整份解析失败且不写入部分快照

### Requirement: 新快照只有通过完整性校验后才能成为当前来源视图
系统 MUST 在写入成功快照前验证三个主分区、必需字段、非空数值和日期格式、活动身份唯一性以及可选顶部表的唯一匹配。页面标题若声明活动数量，该数量 MUST 等于三个主分区解析总数。任一阻断校验失败时 MUST 保留上一成功快照作为当前视图，不得写入部分活动或制造批量移除。

#### Scenario: 页面标题数量与表格不一致
- **WHEN** 标题声明 18 条活动但三个主分区只解析到 17 条
- **THEN** 本次解析失败，上一成功快照继续作为当前视图且失败原因可观察

#### Scenario: 顶部行无法唯一匹配
- **WHEN** 存在顶部推荐行但它无法匹配或同时匹配多个主活动
- **THEN** 本次解析失败且不得把该行静默丢弃或创建重复活动

#### Scenario: 页面明确没有当前活动
- **WHEN** 页面明确声明零活动且三个主分区结构完整并且均无活动行
- **THEN** 系统可以保存零活动成功快照，并将上一快照中的活动通过 Diff 表达为移除

#### Scenario: 零行但缺少可信数量信号
- **WHEN** 页面未声明零活动且三个主分区合计没有解析到活动行
- **THEN** 系统把结果视为可能截断或改版并拒绝成为成功快照

### Requirement: 当前列出状态与截止日期状态必须分离
系统 SHALL 只从当前解析器版本的最新成功快照构建当前活动列表。活动是否仍由来源列出 MUST 由其是否存在于该快照决定；截止日期状态 MUST 在读取时按北京时间自然日计算为 `ACTIVE`、`EXPIRED` 或 `UNKNOWN`，不得用截止状态覆盖来源列出状态。

#### Scenario: 当前活动有未来或当天截止日期
- **WHEN** 活动存在于最新成功快照且北京时间当前日期不晚于 `deadline_date`
- **THEN** 读取结果返回 `is_currently_listed=true` 和 `deadline_status=ACTIVE`

#### Scenario: 当前活动没有截止日期
- **WHEN** 活动存在于最新成功快照但没有 `deadline_date`
- **THEN** 读取结果返回 `is_currently_listed=true` 和 `deadline_status=UNKNOWN`

#### Scenario: 已过期活动仍在页面中
- **WHEN** 活动存在于最新成功快照但北京时间当前日期已晚于 `deadline_date`
- **THEN** 读取结果保留 `is_currently_listed=true`、返回 `deadline_status=EXPIRED` 并暴露来源时效异常，不擅自删除该活动

#### Scenario: 活动从新成功快照消失
- **WHEN** 活动存在于上一成功快照但不存在于最新成功快照
- **THEN** 它退出当前列表但仍可在历史中查询，前后快照 Diff 将其标记为 `REMOVED`

### Requirement: 系统必须提供当前、历史和快照变化读取
系统 SHALL 提供读取最新成功快照、当前活动列表、按 `offer_key` 查询结构化历史以及比较相邻成功快照的服务或等价 CLI。Diff MUST 将活动划分为 `ADDED`、`CHANGED`、`REMOVED` 或 `UNCHANGED`，并保留来源页面版本与观察时间。

#### Scenario: 查询当前活动
- **WHEN** 消费者请求 AwardWallet 当前买分活动
- **THEN** 系统只返回最新成功快照中的活动、该快照来源时间和截止日期状态，不混入旧快照活动

#### Scenario: 查询一个项目的历史
- **WHEN** 消费者使用 `offer_key` 查询历史
- **THEN** 系统按时间返回该项目在各成功快照中的结构化字段和对应 DocumentVersion

#### Scenario: 比较相邻快照
- **WHEN** 两份相邻成功快照具有新增项目、字段变化和消失项目
- **THEN** Diff 分别返回 `ADDED`、`CHANGED` 和 `REMOVED`，物质字段未变化的共同项目返回 `UNCHANGED`

### Requirement: 买分处理必须独立接入每日自动化和手工运行
系统 MUST 在每日单轮中采集并确定性处理该来源，保存独立处理摘要，并与 LoyaltyLobby、StatusMatch 和生命周期阶段故障隔离。系统 SHALL 提供只采集、只处理、采集加处理、当前读取和历史读取的手工入口；买分组合运行 MUST NOT 要求可用 AI 凭证。

#### Scenario: 每日处理成功
- **WHEN** 自动化收集到新的或尚未解析的 AwardWallet 页面版本
- **THEN** 同一周期在有界数量内生成或复用买分快照，摘要报告选择、成功、失败、复用和最新活动数，模型调用计数保持不变

#### Scenario: 买分解析失败
- **WHEN** AwardWallet 页面获取成功但结构化解析失败
- **THEN** 系统记录来源或处理错误并保留上一成功快照，LoyaltyLobby、StatusMatch 和生命周期阶段继续运行

#### Scenario: 其他来源失败
- **WHEN** LoyaltyLobby 或 Gmail 来源在同一周期失败
- **THEN** AwardWallet 固定页面仍可独立采集和解析，失败来源不阻塞该链路

#### Scenario: 手工组合运行
- **WHEN** 操作者运行 AwardWallet 买分来源的采集加处理命令且没有 AI 凭证
- **THEN** 系统完成固定页面抓取与确定性快照处理，并输出结构化运行摘要

### Requirement: 买分领域不得污染会籍业务数据
系统 MUST NOT 为 AwardWallet 买分页面或其活动创建 `StatusEvent`、`ArticleOpportunityRecord`、StatusMatch 项目、FactSet、第三方 supplement、文章简报或会籍图贡献。买分模块与会籍模块只可以在自动化组合入口和未来只读产品投影处汇合。

#### Scenario: 买分页面处理完成
- **WHEN** 一个买分页面版本成功产生结构化快照和活动
- **THEN** 会籍事件、普通文章机会、StatusMatch 事实和会籍图数据均不发生变化

#### Scenario: 页面同时提到会籍或信用卡
- **WHEN** AwardWallet 汇总页的辅助正文包含会籍、信用卡或其他旅行建议
- **THEN** 买分解析器仍只物化三个主买分区块，不把辅助正文路由到会籍或通用文章处理
