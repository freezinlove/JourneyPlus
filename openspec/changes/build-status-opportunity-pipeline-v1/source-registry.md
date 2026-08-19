# 第一版来源注册表

> 文档状态：第一版实施输入；来源入口与技术特征已核验，采集频率和正式启用顺序待用户决定
>
> 最近核验：2026-08-19
>
> 业务范围：仅发现会籍获取、升级或延期机会；来源出现的其他主题仍由后续 AI 相关性判断排除

## 1. 全局默认值

| 字段 | 第一版值 |
|---|---|
| `topic_scope` | `STATUS_ACQUISITION` |
| `collection_cadence` | `null` |
| `automatic_scheduling` | `false` |
| `registration_state` | `SELECTED`；实现后允许手工测试，正式启用仍须满足各项访问条件 |
| `discovery_mode` | 仅使用本注册表列明的 Feed、公开目录页、公开报告页或只读邮件 |
| `official_page_following` | 不主动跟踪；只保留来源材料给出的行动链接，供证据展示或人工核验 |
| `raw_retention` | 服从每个来源的保存策略；不确定时只保存必要内容、哈希、元数据和链接 |

来源适配器只负责发现和获取，不判断文章是否相关，也不创建 `StatusEvent`。统一输出至少包含：

```text
source_id
external_id
discovered_url
canonical_url
title
published_at / observed_at
raw_metadata
raw_body 或来源策略允许的必要内容
content_type
```

## 2. 八组来源总览

这里保留用户确定的八组接入范围。StatusMatch 与 GetStatus 共用专用收件别名、Gmail 标签和邮件适配器，因此在数据库中注册为一条邮件来源；可选的 `origin_provider` 只用于区分品牌归属，不参与邮件准入。

| 序号 | `source_id` | 来源 | 发现入口 | 适配器 | 正文策略 |
|---|---|---|---|---|---|
| 1 | `ffb_elite_status_feed` | Frequent Flyer Bonuses 博客 | [Elite Status RSS](https://blog.frequentflyerbonuses.com/category/elite-status/feed) | `FeedAdapter` | Feed 摘要发现，再读取文章页 |
| 2 | `ffb_status_match_catalog` | Frequent Flyer Bonuses 会籍汇总页 | [Status Match & Fast Track Offers](https://www.frequentflyerbonuses.com/statusmatchoffers.html) | `StaticCatalogAdapter` | 将每条顶层活动记录作为独立材料 |
| 3 | `awardwallet_elite_status_feed` | AwardWallet Elite Status | [Elite Status RSS](https://awardwallet.com/blog/tag/elite-status/feed/) | `FeedAdapter` | Feed 摘要发现，再读取文章页 |
| 4 | `status_services_mail` | StatusMatch 与 GetStatus 邮件 | Gmail `statusmatch` 标签与专用收件别名 | `MailAdapter` | 一条只读邮件来源；不以网站抓取替代邮件 |
| 5 | `statusmatcher_reports` | StatusMatcher | [最新报告目录](https://statusmatcher.com/) | `StatusMatcherAdapter` | 目录发现数字报告 ID，再读取公开报告页 |
| 6 | `loyaltylobby_feed` | LoyaltyLobby | [全站 RSS](https://loyaltylobby.com/feed/) | `FeedAdapter` | 仅使用 Feed 正文，不抓文章页 |
| 7 | `frequentmiler_elite_status_feed` | Frequent Miler Elite Status | [Elite Status RSS](https://frequentmiler.com/category/travel/elite-status/feed/) | `FeedAdapter` | 使用 Feed 正文，不需要文章页 |
| 8 | `verylvke_feed` | 飞常旅客 VERYLVKE | [全站 RSS](https://www.verylvke.com/feed/) | `FeedAdapter` | 使用 Feed 正文；一篇可产生多个候选事件 |

## 3. 逐项注册信息

### 3.1 `ffb_elite_status_feed`

- 人类入口：[Frequent Flyer Bonuses](https://blog.frequentflyerbonuses.com/)
- 栏目页：[Elite Status Archives](https://blog.frequentflyerbonuses.com/category/elite-status/)
- 发现入口：`https://blog.frequentflyerbonuses.com/category/elite-status/feed`
- 已核验特征：RSS 2.0；当前每条含 `guid`、文章链接和摘要，不含 `content:encoded` 全文。
- 稳定 ID：优先使用 RSS `guid`，回退到规范化文章 URL。
- 获取方式：Feed 只负责发现；正文从同域文章链接读取。
- URL 规范化：去除片段和已知跟踪参数，保存重定向后的最终 URL；原始 Feed URL仍保留在元数据中。
- 保存限制：不转载全文；对外只输出原创简报、短证据定位和明确来源链接。
- `collection_cadence: null`

### 3.2 `ffb_status_match_catalog`

- 人类及发现入口：`https://www.frequentflyerbonuses.com/statusmatchoffers.html`
- 已核验特征：公开静态 HTML，按航空、酒店和租车分区，一页包含多条活动及页面更新时间。
- 稳定 ID：`section + normalized_program_name + canonical_primary_action_url`；无行动链接时使用 `section + normalized_program_name + normalized_record_text_hash`。
- 变更 ID：对单条规范化记录计算 `record_hash`，只为变化记录创建新 `DocumentVersion`。
- 获取方式：只解析各分区的顶层活动记录；列表中的资格细节属于父记录，不能误拆成多个机会。
- 保存字段：页面更新时间、分区、项目名称、记录正文、行动链接、记录哈希和观察时间。
- `collection_cadence: null`

### 3.3 `awardwallet_elite_status_feed`

- 人类入口：`https://awardwallet.com/blog/tag/elite-status/`
- 发现入口：`https://awardwallet.com/blog/tag/elite-status/feed/`
- 已核验特征：RSS 2.0；当前每条含带 `pubDate` 查询参数的文章链接与摘要，不含 `content:encoded` 全文。
- 稳定 ID：移除 `pubDate` 及其他跟踪参数后的规范化文章 URL；原始 RSS `guid` 作为来源元数据保留。
- 获取方式：Feed 只负责发现；使用去除 `pubDate` 后的同域文章 URL 获取正文。
- 业务注意：该标签同时包含会籍权益、常规定级攻略等大量非机会内容，适配器不得以标题关键词过滤，统一交给 `StatusRelevanceAnalyzer`。
- `collection_cadence: null`

### 3.4 `status_services_mail`

- 来源身份：[StatusMatch](https://www.statusmatch.com/) 与 [GetStatus](https://www.getstatus.com/)
- Gmail 账户：`kirikoomiku@gmail.com`
- 专用收件别名：`kirikoomiku+statusmatch@gmail.com`
- 现有 Gmail 过滤器：匹配 `to:(kirikoomiku+statusmatch@gmail.com)`，应用标签 `statusmatch`；StatusMatch 与 GetStatus 均使用这条过滤路径。
- 发现入口：Gmail 标签 `statusmatch` 与上述收件别名的交集；没有公开 Feed URL，也不扫描其他标签或普通收件箱。
- 适配器：Gmail API + OAuth 2.0，仅申请 `https://www.googleapis.com/auth/gmail.readonly`，不得申请 `gmail.modify`、`gmail.settings.*` 或完整 `https://mail.google.com/` 权限。
- 查询方式：先用 `users.labels.list` 将标签名 `statusmatch` 解析为标签 ID，再用 `users.messages.list(userId="me", labelIds=[statusmatch_label_id], q="to:(kirikoomiku+statusmatch@gmail.com)")` 发现消息；逐条通过 `users.messages.get` 读取必要内容。
- 来源记录：两类邮件统一使用 `status_services_mail`；系统可以根据主题、可见品牌和主要链接记录可选的 `origin_provider = STATUSMATCH | GETSTATUS | UNKNOWN`，但该字段不影响是否接收或继续处理。
- 条目稳定 ID：`status_services_mail + gmail_message_id`；同时保存 RFC `Message-ID` 用于跨导入核对。
- 获取方式：读取允许邮件的必要头部、纯文本/HTML 正文和正文链接；第一版不自动处理附件中的未知文件类型。
- 安全边界：不得发送、回复、移动、删除、标记、修改邮件或更改现有 Gmail 过滤器；Access Token、Refresh Token 和邮件正文不得进入日志。`gmail.readonly` 在 OAuth 层面可读取整个邮箱，因此“标签 + 收件别名”是应用必须强制执行并测试的访问边界。
- 准入规则：凡同时满足 `statusmatch` 标签和专用收件别名条件的邮件均可进入后续流程，不再设置真实发件人白名单。
- 启用条件：Google OAuth 客户端和只读授权配置完成。
- Gmail API 依据：[列出邮件](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)、[OAuth 权限范围](https://developers.google.com/workspace/gmail/api/auth/scopes)。
- `collection_cadence: null`

### 3.5 `statusmatcher_reports`

- 人类及最新发现入口：`https://statusmatcher.com/`
- 分页模板：`https://statusmatcher.com/?page={page}`；实现时从首页开始并跟随页面实际的 Next 链接，不能假定最大页数。
- 报告正文模板：`https://statusmatcher.com/report/{numeric_report_id}`
- 辅助目录：[航空](https://statusmatcher.com/airlines)、[酒店](https://statusmatcher.com/hotels)、[租车](https://statusmatcher.com/auto)。辅助目录只用于主体名称提示，不替代最近报告发现。
- 稳定 ID：公开报告 URL 中的数字 `report_id`。
- 已核验特征：目录和报告均为服务端渲染 HTML；报告包含结果类型、来源会籍、目标项目、用户叙述和日期。
- 业务注意：内容为用户提交的个案，不能单独视作仍然有效的正式活动规则；需要 AI 判断并保留来源时间与不确定性。
- 访问限制：[Terms and Conditions](https://statusmatcher.com/terms) 声明内容版权和复用限制。自动化实现可以规划和制作解析夹具，但正式持续采集、保存范围及对外衍生输出必须先完成人工合规确认；不得保存或输出用户身份信息。
- `collection_cadence: null`

### 3.6 `loyaltylobby_feed`

- 人类入口：`https://loyaltylobby.com/`
- 发现与正文入口：`https://loyaltylobby.com/feed/`
- 已核验特征：RSS 2.0；当前条目包含 `guid`、文章链接、摘要和 `content:encoded` 正文。
- 稳定 ID：优先使用 RSS `guid`，回退到移除 `omhide` 等展示/跟踪参数后的规范化文章 URL。
- 获取方式：只使用 RSS 内正文；不得继续请求文章页。核验时文章页返回 403，且其 `robots.txt` 明确限制多类 AI/自动化客户端。
- 保存限制：遵守 Feed 提供范围，保存必要正文或快照用于内部分析；对外只提供原创简报和原文章链接。
- `collection_cadence: null`

### 3.7 `frequentmiler_elite_status_feed`

- 人类入口：`https://frequentmiler.com/`
- 栏目页：`https://frequentmiler.com/category/travel/elite-status/`
- 发现与正文入口：`https://frequentmiler.com/category/travel/elite-status/feed/`
- 已核验特征：RSS 2.0；当前条目包含 `guid`、文章链接、摘要和 `content:encoded` 正文。
- 稳定 ID：优先使用 RSS `guid`，回退到规范化文章 URL。
- 获取方式：使用 RSS 正文，不需要继续抓取文章页；文章 URL作为出处和行动入口保留。
- 业务注意：Elite Status 栏目仍含权益介绍和常规定级攻略，适配器不得提前做业务关键词过滤。
- `collection_cadence: null`

### 3.8 `verylvke_feed`

- 人类入口：`https://www.verylvke.com/`
- 发现与正文入口：`https://www.verylvke.com/feed/`
- 已核验特征：全站 RSS 2.0；当前条目包含 `guid`、文章链接、摘要和 `content:encoded` 正文。
- 稳定 ID：优先使用 RSS `guid`，回退到规范化文章 URL。
- 获取方式：使用 RSS 正文，不需要继续抓取文章页。
- 业务注意：来源覆盖主题很广，且一篇中文文章可能并列多个活动。相关性分析允许一份 `DocumentVersion` 产生零个、一个或多个最小 `event_hints`，后续每个提示分别进入事件关系判断。
- `collection_cadence: null`

## 4. 实施约束

1. 实现时 MUST 以本注册表的 `source_id` 作为稳定配置键，不以网站显示名称作为外键；八个来源组共导入八条来源记录。
2. URL 变化、Feed 失效或访问策略变化时，先更新本注册表和解析夹具，再修改适配器；不得在业务模块散落替代 URL。
3. `collection_cadence` 在用户明确决定前保持 `null`，注册表核验日期不代表调度频率。
4. 来源注册与正式启用是两个状态；入口已核验不代表已完成法律、版权或生产访问审批。
5. 新增来源或把当前来源扩展到其他主题，需要单独修改 OpenSpec，不得借第一版适配器顺带扩大业务范围。
