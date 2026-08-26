## Context

JourneyPlus 当前已经具备来源注册、适配器、`SourceItem`、`DocumentVersion`、原文清理、内容哈希、采集运行、每日数据库租约、来源故障隔离和自动化状态等通用底座。当前通用文章 V2 只处理 `loyaltylobby_feed`，其领域语义明确限定为会籍获取机会；积分、里程和普通折扣会被判为 `NONE`。StatusMatch 官方与第三方链路还承担项目页面监控、事实、简报和会籍图职责，同样不适合买分活动。

本变更只监控一个固定公开页面：

```text
https://awardwallet.com/news/current-promotions-buy-points-miles/
```

该页面当前由服务端 HTML 直接输出完整活动列表，不需要浏览器渲染。完整列表位于航空、酒店和其他交通三个 `purchase-times` 区块；顶部 TablePress 表格只是推荐子集，但额外提供部分活动的每分购买价格。主表中的部分活动没有截止日期，详情页和购买入口也可能指向 AwardWallet 站内跳转或外部购买网站。

目标架构为：

```text
固定 AwardWallet URL
        │
        ▼
SinglePageAdapter ──▶ SourceItem + DocumentVersion
                              │
                              ▼
                    确定性 DOM 解析与校验
                              │
                              ▼
                BuyPointsSnapshot + BuyPointsOffer[]
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
          最新成功快照读取           历史与前后快照 Diff

会籍文章 / StatusMatch / 会籍图 ─────────────── 保持不变
```

## Goals / Non-Goals

**Goals:**

- 每日重新请求唯一目标 URL，内容不变时复用现有文档版本，内容变化时保留新版本。
- 不使用 AI，确定性提取页面当前列出的全部买积分/里程活动及可直接读取的字段。
- 原始网页、清理正文、结构化快照和快照活动均可追溯，且新页面版本不覆盖旧结构化结果。
- 只有完整且自洽的解析结果可以成为最新成功快照；页面改版、截断或数量不一致时保留上一成功快照。
- 明确区分来源是否仍列出活动、活动是否有截止日期以及截止日期是否已过。
- 复用当前每日自动化、来源故障隔离、运行摘要和 CLI 习惯，同时证明该链路不消耗模型调用预算。
- 为以后统一机会流、用户匹配和购买价值计算提供稳定的结构化输入，但不提前实现这些消费者。

**Non-Goals:**

- 不抓取 AwardWallet Feed、标签页、详情页、购买页或目标 URL 之外的任何发现来源。
- 不跟随 `detail_url` 或 `action_url`，不执行登录、购买、注册、表单提交或可用性验证。
- 不使用大模型生成活动、补全空字段、翻译、摘要或购买建议。
- 不将结果写入 `StatusEvent`、`ArticleOpportunityRecord`、StatusMatch FactSet、第三方 supplement 或会籍映射树。
- 不在第一版判断活动是否值得购买，不计算积分估值、兑换价值或对具体用户和旅行的影响。
- 不把项目名称统一到全产品主数据，不处理同一项目同时存在多个定向购买报价的通用建模问题。
- 不承诺比目标页面更实时或更准确；系统只忠实记录该页面在观察时公开列出的内容。

## Decisions

### 1. 业务处理使用独立确定性领域链路，共享现有采集底座

新增 `buy_points` 领域包，负责契约、DOM 解析、持久化、读取和处理编排。来源和文档仍使用现有通用模型：

```text
sources/
├── single_page.py       # 固定单页发现和获取
└── registry.py          # awardwallet_buy_points_page

buy_points/
├── contracts.py         # 严格解析结果和读取模型
├── parser.py            # AwardWallet 确定性 DOM 解析
├── service.py           # 快照物化、当前读取和 Diff
└── operations.py        # 待处理选择、幂等和运行汇总
```

组合入口可以同时调用通用文章、StatusMatch 和买分处理器，但三个领域包彼此不导入。买分结果不会伪装成会籍机会，也不会为了复用现有表而填入没有意义的会籍字段。

替代方案是扩展普通文章 Prompt 和 `ArticleOpportunityRecord`。这会把结构化页面交给 AI、消耗一次正文加每活动一次简报调用，并受到当前每篇最多 20 个机会的限制，因此不采用。

### 2. 固定页面适配器每天发现同一个稳定 SourceItem

来源注册项使用：

```text
source_id: awardwallet_buy_points_page
adapter_type: single_page
content_strategy: fetch_article
collection_cadence: P1D
automatic_scheduling: true
```

`SinglePageAdapter.discover()` 每次只返回一个 `DiscoveredItem`：

- `external_id` 使用稳定的来源内常量或规范化 canonical URL，不使用标题、更新时间或活动数量；
- `canonical_url` 和 `discovered_url` 均为唯一目标 URL；
- `refresh_on_discovery=true`，确保每天重新请求页面；
- 不从页面链接继续发现其他条目。

`fetch()` 使用现有 `Fetcher` 请求该 URL并接受正常同站重定向，最终 URL 必须仍是预期 AwardWallet 页面；不请求正文中的任何链接。HTTP 超时、状态错误或最终 URL 越界按来源采集失败处理。

现有 `IngestionService` 继续依据原始哈希或规范化哈希复用文档版本。因此“每天重新请求”不会变成“每天制造一份重复文档”。

### 3. 原始页面版本和业务快照分层保存

`DocumentVersion.raw_body` 保存原始 HTML，`normalized_body` 使用 AwardWallet `article` 选择器及现有广告、目录、信用卡组件等排除规则生成可读正文。买分解析器必须读取 `raw_body`，因为 Markdown 清理会丢失用于分区和字段定位的 CSS class；规范化正文继续服务内容哈希、人工阅读和审计。

新增两张表：

```text
BuyPointsSnapshotRecord
├── id
├── source_item_id
├── document_version_id
├── parser_version
├── page_title
├── page_modified_at
├── advertised_offer_count
├── parsed_offer_count
├── offers_signature
└── created_at

BuyPointsOfferRecord
├── id
├── snapshot_id
├── offer_key
├── category
├── program_name
├── offer_text
├── offer_kind / max_percent
├── purchase_rate_raw / purchase_rate_cents
├── deadline_raw / deadline_date
├── posting_time_raw
├── detail_url / action_url
├── top_pick
└── evidence
```

快照与活动一经成功写入即不可变。`(document_version_id, parser_version)` 唯一，`(snapshot_id, offer_key)` 唯一。解析失败不创建半成品快照；失败、重试次数和安全错误摘要使用现有 `JobRun` 及每日处理摘要记录。解析器版本升级可以为同一 DocumentVersion 生成一个新版本的结构化快照，旧快照保留。

`evidence` 保存分区标识、页面行中的项目、活动、日期、价格和链接原文；它不复制整个页面，也不把购买入口当作已经验证的官方事实。完整来源仍由 `document_version_id` 回溯。

### 4. 主活动区块是完整库存，顶部表格只做可选补充

解析器按标题锚点或明确的相邻结构识别三个主区块：

- `Buy Miles Promotions From Airlines` → `AIRLINE`
- `Buy Points Promotions From Hotels` → `HOTEL`
- `Buy Points Promotions From Other Transportation` → `OTHER`

每个主区块中的非表头 `.pt-row` 产生一条活动。字段映射为：

- `.pt-program` → `program_name`
- `.pt-comment` 的完整可见文字 → `offer_text`
- `.pt-comment a[href]` → `detail_url`
- `.pt-date` → `deadline_raw` 和可选 `deadline_date`
- `.pt-avg` 的可见文字或 `title` → `posting_time_raw`
- `.pt-how a[href]` → `action_url`

顶部 `tablepress-1310` 不是完整列表，不得单独创建活动。若存在，解析器使用规范化 `action_url` 优先、规范化项目名次之，将顶部行匹配到主活动，并补充 `top_pick=true`、`purchase_rate_raw` 和 `purchase_rate_cents`。匹配必须唯一；顶部行无法匹配或匹配到多个主活动时整份解析失败。顶部表格不存在时仍可生成完整主表快照，但所有活动的顶部补充字段保持空，并记录非阻断诊断。

页面中的相对链接使用唯一页面 URL 转为绝对 URL；系统只保存链接，不解析跳转目标。原始 href 可保存在 evidence 中供审计。

### 5. 结构化数值采用“原文优先、有限规范化”

每条活动必须保存页面原始活动文字。确定性正则只在明确格式下补充：

- `bonus` → `offer_kind=BONUS`
- `discount` → `offer_kind=DISCOUNT`
- 百分比 → `max_percent`
- 顶部购买价格如 `1.5¢` → 十进制 `purchase_rate_cents`
- 日期如 `8/27/26` 或 `August 27, 2026` → `deadline_date`

无法识别的非空活动类型、百分比、购买价格或日期不得猜测。核心字段无法规范化时解析失败并保留上一成功快照；页面允许为空的截止日期和购买价格分别保存为空。日期只表示来源给出的日历日期，不推断 AwardWallet、项目或购买平台时区；读取时按照项目既有规则，以北京时间自然日结束作为展示有效边界。

不把 `up to`、定向资格或价格分档从文字中丢弃。第一版以 `offer_text` 为完整语义，`offer_kind` 和数值字段只是检索与排序辅助。

### 6. 稳定活动身份来自主行链接，变化通过快照表达

`offer_key` 依次使用：

1. 规范化 `detail_url` 的 host + path；
2. 规范化 `action_url` 的 host + path；
3. `category` 与规范化 `program_name` 的稳定摘要。

截止日期、折扣比例、活动文字和 Top 推荐状态不得进入身份键，否则延期、优惠变化或推荐变化会被误认为另一个项目。同一成功快照内出现重复键视为结构歧义并失败。

当前页面通常每个项目只有一条活动。若未来同一稳定链接同时出现多条不同报价，本变更选择失败并报警，而不是静默合并；届时再根据真实页面结构扩展活动周期或定向报价身份。

### 7. 最新成功快照是当前来源视图，时间状态按读取时计算

读取服务按解析器版本选择该 SourceItem 最新创建的成功快照。解析失败或采集失败不改变当前视图。当前活动只来自该快照；旧快照中的活动不会混入当前列表。

来源列出状态与截止日期状态分开表达：

```text
is_currently_listed = 活动是否存在于最新成功快照

deadline_status =
  UNKNOWN   deadline_date 为空
  ACTIVE    北京时间当前日期 <= deadline_date
  EXPIRED   北京时间当前日期 > deadline_date
```

活动在最新快照中存在但日期已经过期时仍保持 `is_currently_listed=true`，同时返回来源时效异常诊断；系统不得擅自把它从来源当前列表删除。活动从下一份成功快照消失时，自然退出当前查询，但所有历史快照保留。

前后两个成功快照按 `offer_key` 计算：

- 新快照独有 → `ADDED`
- 两者都有且物质字段签名变化 → `CHANGED`
- 旧快照独有 → `REMOVED`
- 两者都有且物质字段相同 → `UNCHANGED`

物质签名覆盖分类、项目显示名、活动原文、规范化数值、截止日期、到账时间、链接和 Top 字段。Diff 可以按需计算，第一版不另建变化事件表。

### 8. 解析必须 fail closed，但允许真实的零活动页面

成功快照至少满足：

- 页面正文和三个主分区均存在；
- 每个活动行均有非空项目名和活动描述；
- 每个非空日期、百分比和购买价格都能按受支持格式解析；
- 主活动 `offer_key` 唯一；
- 顶部表格若存在，其行都能唯一匹配主活动；
- 页面标题若包含声明活动数量，必须与三个主分区总行数相等。

若页面明确声明零活动且三个空主分区结构完整，系统可以保存零活动成功快照。若没有数量信号且解析结果为零，系统视为可能截断或改版并失败。校验失败不得写入部分活动、不得把现有活动批量标成移除，也不得推进“最新成功快照”。

替代方案是逐行容错并发布剩余活动。这会在页面局部改版时制造大量假下架，违背监控系统的可信度目标，因此不采用。

### 9. 每日自动化增加独立确定性阶段，不改变 AI 预算

每日单轮先按现有方式收集启用来源，再调用买分处理器选择没有当前解析器快照的 AwardWallet DocumentVersion。处理有界并幂等；相同文档和解析器版本重跑不重复创建快照或活动。

自动化摘要新增买分字段，至少报告：选择文档数、成功/失败/复用数、最新活动数、解析器警告和安全错误。来源采集失败继续由当前来源隔离处理；买分解析失败不得阻塞 LoyaltyLobby、StatusMatch 或适用的生命周期推进。买分处理不得调用 `AIProvider`，`model_calls` 和各 AI 分项计数不因该阶段增加。

CLI 提供：

- `collect awardwallet_buy_points_page`：只采集固定页面；
- `process-buy-points`：处理待解析页面版本；
- `run-source awardwallet_buy_points_page`：采集并确定性解析，不要求 AI 凭证；
- `buy-points-current`：输出最新成功快照当前列表；
- `buy-points-history <offer-key>`：输出指定活动的结构化历史。

命令名在实现时可以按现有 CLI 一致性微调，但必须保留等价的采集、处理、组合运行、当前读取和历史读取能力。

### 10. 验收使用固定夹具与一次受控真实页面检查

自动化测试使用最小化、脱敏的固定 HTML fixture，覆盖当前页面的三种分区、顶部子集、相对/绝对链接、有/无截止日期以及页面结构失败，不把实时互联网作为测试套件前置条件。

实现完成后执行一次受控真实页面 smoke：核对标题声明数、三个分区计数、顶部匹配数、代表性字段、原文证据和第二次运行幂等。真实活动数量和具体优惠不是永久测试常量，只在验收记录中保存观察时间和当时结果。

## Risks / Trade-offs

- [AwardWallet 修改 class、标题或区块结构] → 使用结构守卫 fail closed，保留上一成功快照，并通过来源错误和自动化摘要暴露；修复解析器时提升 parser version。
- [页面响应被 CDN 缓存或更新滞后] → 记录实际观察时间和页面更新时间，只声称“来源当前列出”，不声称项目官网实时状态。
- [页面标题数量暂时与表格不一致] → 拒绝新快照，避免把截断页面解释为活动移除；运营者可检查原文后决定是否调整规则。
- [详情链接或 affiliate action link 改变导致 offer_key 改变] → 优先使用详情 URL，保留前后快照和 evidence；第一版 Diff 可能显示 remove + add，后续有真实案例再增加显式别名。
- [空截止日期活动长期保留] → 返回 `UNKNOWN` 而不是推断永久有效；是否继续列出由最新成功快照决定。
- [不抓详情页导致缺少完整价格分档和资格] → 原文和链接保留，第一版只展示汇总页可证实字段；需要价值判断时另建变更。
- [整页 fail closed 降低局部数据可用性] → 这是有意取舍，优先避免假下架；上一成功快照和失败时间同时展示，消费者可以识别数据新鲜度。

## Migration Plan

1. 新增 ORM 模型和 Alembic 迁移，只创建买分快照与活动表、唯一约束和索引，不修改现有会籍或文章业务表。
2. 增加固定单页适配器、来源注册和正文清理规则，先保持 `automatic_scheduling=false` 完成本地夹具测试。
3. 实现解析、快照、读取、Diff 和 CLI，使用目标 URL执行一次手工 `collect` 与 `process-buy-points` 验收。
4. 在开发 PostgreSQL 验证首次采集、内容不变重跑、解析器幂等、失败保护和迁移降级。
5. 接入每日自动化摘要和故障隔离，确认模型调用计数不变后启用该来源的 P1D 自动调度。
6. 更新 README/运维文档，记录唯一 URL、零 AI 边界、当前/截止状态语义、失败检查和回滚方法。

回滚时先关闭来源的自动调度和买分处理入口。代码可以回滚而保留新增表及历史原文；若确需数据库降级，迁移只删除本变更新增的两张派生表，不删除 `Source`、`SourceItem`、`DocumentVersion`、CollectionRun 或任何会籍数据。未经用户明确授权不得清理已采集历史。

## Open Questions

当前没有阻塞实施的问题。项目主数据统一、活动详情页复核、AI 中文摘要、积分估值、用户匹配和统一机会流属于后续独立变更，不能在本变更实现时顺带扩张。
