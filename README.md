# JourneyPlus

> **当前目标架构**：[目标架构与模块职责](doc/target-system-architecture.md)。两个板块：AIWorkflow 生产并存储正式知识，提供简报和完整匹配图；Agent 消费同一数据库中的知识并引用简报。正式业务模型采用当前 AIWorkflow 产出结构，保留业务数据，按实际缺口增量修复。已完成部分适配和分项验证，整体目标仍须按文档要求验收；不再以清库重建为实施前提。

## 当前运行入口

正常产品启动：`uv run journeyplus product-api`。使用当前 AIWorkflow 数据库，不需要选择 legacy/unified/rollback 模式；旧 `JOURNEYPLUS_KNOWLEDGE_READ_MODE` 环境变量已退出。

- `/holdings` 管理会籍，`/matches` 查看匹配图，`/briefs` 查看简报。
- `/knowledge` 和 `/explore` 使用同一正式模型读取知识、查询路径。
- `/workspace` 使用 Agent。模型按需选择工具和图卡，回复为自然语言。
- 独立知识服务：`uv run python -m journeyplus.product.knowledge_server --port 8014`，无需启动模型。
- `JOURNEYPLUS_KNOWLEDGE_USER_WRITES_PAUSED=true` 仅暂停会籍和等待任务的用户变更，不切换数据模型或关闭知识读取。

费用信息未提供时按免费处理；地区只作适用范围和价格说明，不排除路径。过期会籍保留记录，但不参与匹配计算。

历史架构、迁移与审计记录继续留档；与当前说明冲突时，以目标架构及当前实现为准。

JourneyPlus 当前收敛为一个默认面向中国用户的个性化常旅客会籍匹配产品。用户从规范化目录选择自己已有的会籍，系统沿现有官方与普通文章映射图计算完整可达关系，匹配图对每个会籍只绘制一次并只展示离已有会籍最近的到达路径；产品同时展示匹配/挑战机会、分路线价格、原文归档和中文简报。中国地区只生成提示，不过滤、不阻止、不替换任何机会或价格。

AIWorkflow 负责事实生产。官方 StatusMatch 的标题与摘要随首次事实提取生成，程序绑定版本并提供简报；普通文章保留独立解释与简报链路。会籍目录、路径遍历、价格展示和页面查询由程序完成。Agent 通过通用 Harness 使用工具、联网和记忆，自主决定查询、比较、展示及后续对话；用户业务变更通过明确操作保存。

机会事实只分为 `STATUS_MATCH | OTHER`：真正的会籍匹配、挑战、Fast Track 和临时会籍挑战属于前者，其他会籍相关机会属于后者。`OTHER` 仍照常生成并展示简报，只是不进入个性化匹配图。

当前通用文章来源只开放 `loyaltylobby_feed`；`status_services_mail` 只进入 StatusMatch 专用项目链路。原有买分/买里程链路继续保留历史、手工采集和查询能力，但已退出默认产品入口和自动调度。产品总边界见 [个性化常旅客会籍匹配产品总方针](doc/personalized-status-match-product-direction.md)，Agent 的定位、工作方式和复杂度边界见 [会籍策略 Agent 产品方针](doc/personalized-status-match-agent-direction.md)，Agent 实现方式见 [会籍策略 Agent 技术基线](doc/personalized-status-match-agent-technical-baseline.md)，启动、接口、迁移和回滚见 [产品运维说明](doc/personalized-status-match-product-operations.md)。

## 本地开发

```bash
uv sync --extra dev
uv run alembic upgrade head
uv run pytest
uv run journeyplus seed-sources
uv run journeyplus collect loyaltylobby_feed --limit 10
uv run journeyplus process-pending --source-id loyaltylobby_feed --limit 10
uv run journeyplus run-source loyaltylobby_feed --limit 10
uv run journeyplus run-source awardwallet_buy_points_page --limit 1
uv run journeyplus process-buy-points --limit 10
uv run journeyplus buy-points-current
uv run journeyplus buy-points-history --limit 20
uv run journeyplus buy-points-diff
uv run journeyplus run-daily
uv run journeyplus automation-status
uv run journeyplus initialize-mail-details
uv run journeyplus initialize-window --start 2026-07-15 --end 2026-07-16
uv run journeyplus ai-smoke
uv run journeyplus gmail-authorize
uv run journeyplus product-api
uv run journeyplus review-api
```

打开 `http://127.0.0.1:8000/workspace` 即可使用会籍策略 Agent；“我的会籍”“匹配图”“机会简报”和“机会详情”仍可独立使用，接口文档位于 `http://127.0.0.1:8000/docs`。Agent 按需读取知识、比较路径、展示图卡、管理明确要求保存的会籍和等待任务，交互步骤由模型决定。`product-api` 启动时会先检查数据库、升级到 Alembic head，并在本地 PostgreSQL 未运行时自动启动项目的 Docker Compose `postgres` 服务。产品当前是本地单用户形态，不包含账号体系。

自动化单元测试可以使用 SQLite；本地真实联调与生产配置使用 PostgreSQL。当前启用每天一次自动调度的来源只有 LoyaltyLobby 通用文章和 StatusMatch 邮件专用来源。AwardWallet 买分来源仍为 `enabled=true`，但 `automatic_scheduling=false`；其他公开来源注册仍在，但 `enabled=false` 且 `automatic_scheduling=false`。

本地 PostgreSQL 使用 Docker Compose，只绑定 `127.0.0.1`。当前默认端口为 `5433`，避免与其他本地项目的 PostgreSQL 冲突：

```bash
docker compose up -d --wait postgres
uv run alembic upgrade head
uv run journeyplus seed-sources
```

`collect` 只负责采集与精确去重，`process-pending` 只处理 LoyaltyLobby 待分析文档，`run-source` 是依次调用采集和对应处理器的薄编排。AwardWallet 来源路由到 `process-buy-points`，即使没有 AI 凭证也可运行；其余普通文章处理规则保持不变。普通文章中已提取的直接会籍映射会与 StatusMatch 官方映射查询时组成同一棵来源中立树；无明确截止日的普通文章映射严格可见 180 天。完整规则见 [统一会籍匹配树说明](doc/unified-membership-tree.md)，买分字段、状态、排障与回滚见 [买分优惠监控运维说明](doc/buy-points-monitoring.md)。

LoyaltyLobby 和 Gmail 使用持久化增量边界。AwardWallet 买分页每轮只发现同一个稳定条目并重新请求唯一 canonical URL，不跟随正文中的详情或购买链接；正文哈希与规范化哈希保证内容不变时复用 `DocumentVersion`，内容变化时才形成新版本和不可变买分快照。

`run-daily` 是供外部定时器调用的单轮命令：它使用数据库租约和北京时间自然日幂等键，隔离来源失败，在上限内处理积压并推进生命周期。`automation-status` 分别显示标题批次、正文理解、文章简报、StatusMatch 项目、第三方补充和买分确定性处理统计；买分阶段不会增加任何模型调用计数。完整 V2 架构、回滚方式与真实验收记录见 [通用文章 V2 运维说明](doc/generic-article-v2.md)。

当前已使用 Codex 本地自动化在每天 09:00 调用该单轮入口；入口从数据库选择当前两条自动来源，并在运行前确保 Docker PostgreSQL 可用。若旧运维记录仍写三条来源，以数据库 `automatic_scheduling` 和本说明为准。配置与检查方式见 [每日自动化 Codex 运维说明](doc/daily-automation-codex.md)。

`initialize-mail-details` 从当前合规 Gmail 邮件中发现并去重项目专属 StatusMatch 链接，读取每个项目的活动首页与 `/faq`，完成处理后等待逐页原文审核。`initialize-window` 是保留的 LoyaltyLobby 历史回放入口，只接受从 `2026-07-15` 到 `2026-08-22` 的固定两日窗口（最后一批为单日），不会采集或处理已关闭的其他公开来源。每批成功后状态停在 `AWAITING_AUDIT`，前一批原文审核没有显式通过时，下一批会被数据库阶段门拒绝；命令本身不会连续推进多个批次。当前产品验收以 Gmail 公开详情页审核和受控真实 LoyaltyLobby V2 批次为准，不要求跑完全部旧窗口。

默认单轮上限可通过环境变量调整：

```bash
JOURNEYPLUS_AUTOMATION_SOURCE_ITEM_LIMIT=100
JOURNEYPLUS_AUTOMATION_DOCUMENT_LIMIT=20
JOURNEYPLUS_AUTOMATION_MODEL_CALL_LIMIT=100
JOURNEYPLUS_AUTOMATION_LEASE_SECONDS=3600
JOURNEYPLUS_GENERIC_ARTICLE_PIPELINE=v2
JOURNEYPLUS_GENERIC_TITLE_DROP_ENABLED=true
```

Agent 已迁移到独立的模型适配器、harness 和工具注册器。旧 v1/v2 Agent 写入口返回 410；历史会话只读，可显式导入新工作区。等待检查由独立 Agent maintenance 运行，不再由每日 Workflow 唤醒。Agent 联网由 `JOURNEYPLUS_AGENT_NETWORK_ENABLED` 独立控制，允许读取公开资料，无须先存在正式路线。

Agent 配置见 `.env.example`，旧三次调用和 StatusMatcher 专用开关已退役。工作区临时资料保留 24 小时，已成功的用户操作回执单独持久保存。

StatusMatcher 读取会清除广告、投稿表单和侧栏等页面杂项，保留报告方向、原文、申请入口及网站翻页链接；原始网页快照继续保留。`web.read` 读取报告时直接返回结构化字段、正文和独立 `report_ref`，统一完成提取与工作区保存，已移除单独的 `research.parse` 工具。模型自行决定是否展示经验卡片或将报告附到路线图、比较卡片；展示阶段不再解析网页。长正文可通过 `web.read` 游标或 `workspace.read` 分段读取，卡片详情显示完整已获取正文。实现与验收见 [报告入口统一验收](doc/statusmatcher-unified-read-acceptance-20260913.md)。

无需调用模型的本地页面可用 `uv run python -m journeyplus.agent.server --no-model` 启动。正常 Agent 启动读取现有配置并初始化模型协议；人工模型席位调试脚本和历史验收记录用于开发排查。当前运行原则以目标架构为准，不沿用历史重构阶段的许可关闭状态。

## 配置

复制 `.env.example` 为 `.env` 后填写服务端配置；程序会自动读取该文件。不要把 API Key、Gmail Access Token、Refresh Token 或 Google OAuth 客户端 JSON 写入仓库。

### 千问 AI 平台

当前默认使用北京按量付费 OpenAI-compatible 地址 `https://dashscope.aliyuncs.com/compatible-mode/v1` 和 `deepseek-v4-flash`。只需在 `.env` 填写北京地域创建的 `JOURNEYPLUS_AI_API_KEY`，然后执行：

```bash
uv run journeyplus ai-smoke
```

该命令只发送一次很小的结构化请求。实现按百炼的 JSON Mode 发送 `response_format={"type":"json_object"}`，并把具体 JSON Schema 放进提示词后使用本地 Pydantic 严格校验字段。JSON Mode 保证返回合法 JSON，本地校验负责固定业务字段与类型。

### Gmail 只读授权

1. 在 Google Cloud Console 创建或选择一个项目，并启用 Gmail API。
2. 在 Google Auth Platform 配置 Branding。个人 Gmail 账户应把 Audience 设为 External；初次测试时把 `kirikoomiku@gmail.com` 加为 Test user。
3. 在 Data Access 中只添加 `https://www.googleapis.com/auth/gmail.readonly`。
4. 在 Clients 中创建 `Desktop app` 类型的 OAuth 2.0 Client，下载客户端 JSON。
5. 将下载文件保存为 `.secrets/google-oauth-client.json`（下载后的原始文件名需要改成这个名称）。这个文件包含客户端密钥，不要发送给别人或提交 Git。
6. 执行 `uv run journeyplus gmail-authorize`。浏览器打开后选择 `kirikoomiku@gmail.com` 并同意只读授权。
7. 程序核对邮箱账号后，把可自动刷新的凭证保存为 `.secrets/gmail-token.json`，文件权限设置为仅当前用户读写。
8. 授权完成后可手工执行 `uv run journeyplus collect status_services_mail`。首次成功会保存 Gmail History ID，后续只读取 History 中新增或后加标签的邮件；游标过期时自动做全量 message ID 对账。适配器会检查新邮件中的文字、按钮和图片链接，本地解开 StatusMatch 跟踪包装，只访问去重后的项目专属 HTTPS 活动首页、`/faq` 与 `/terms`；不会请求包含收件人参数的跟踪中转地址。三页共同组成当前项目快照，`/terms` 的平台公共条款会在哈希和入库前截断。

本项目的 OAuth Audience 已在 2026-08-23 确认为 Production，当前只读刷新令牌已通过四封合规邮件的发现、清洗、完整分析和重复采集验证。若以后重新创建 OAuth 项目，Testing 状态的 External 测试用户授权可能较快失效，长期自动运行前仍须重新确认发布状态和刷新令牌。

### 公开来源只读冒烟

```bash
uv run python scripts/smoke_public_sources.py
```

该命令只验证无需账号的公开来源适配器是否还能发现材料并取得首条正文，不写数据库、不调用 AI，也不测试 Gmail；这不代表被关闭的来源会进入自动调度或通用 V2。

当前确定性产品底座的已完成 OpenSpec 位于 `openspec/changes/converge-personalized-status-match-product/`；当前 Agent 的实施与验收任务位于 `openspec/changes/decouple-agent-harness-and-tools/`。其他历史变更仍保留在原 OpenSpec 目录中；范围冲突时，以当前目标架构和用户已确认的业务规则为准。

## 当前已知限制

- 每日单轮命令、数据库租约、北京时间日桶、限额、故障隔离和状态报告已经实现；当前只允许 LoyaltyLobby 通用链路和 StatusMatch/GetStatus Gmail 专用链路被自动选择，买分保留手工运行，其他公开来源保持关闭。
- LoyaltyLobby 首次采集从北京时间 2026-09-09（含当天）开始，成功后按 Feed GUID 增量；内部排他基线设为 2026-09-08；Gmail 已按持久化 History ID 增量，过期时安全回退全量 ID 对账。两类游标都只在不会遗漏材料的成功边界推进。
- LoyaltyLobby 普通文章在入库前完成标题预筛及正文最终判断；RSS 正文暂存在内存，只有会籍机会文章保存正文、原文快照和结构化结果。无关文章只留极简去重标记，失败或不确定时不推进到该文章之后。`collect loyaltylobby_feed` 也使用配置的模型执行此判断，不能绕过筛选直接归档；普通文章后续生产复用已保存的提取结果。RSS 正文带精确 StatusMatch 官方项目链接的文章按链接直接归类，跳过上述两个模型判断，仍走原有官网关联与补充链路。
- 活动申请窗口、北京时间规范化、独立生命周期和过期软归档已接入每日单轮编排。
- Gmail 在首次部署时需要 Desktop OAuth 客户端 JSON 和浏览器授权；实现会安全保存并自动刷新只读令牌。
- 阿里云百炼真实调用需要北京地域 API Key；在配置密钥前仓库测试只使用结构化模拟响应。
- 本地真实联调与生产目标均使用 PostgreSQL；自动化单元测试继续使用 SQLite 兼容路径，并另外通过 Docker PostgreSQL 验证真实迁移与运行行为。
- 第一期65份冻结金标已完成 v4 最终确认；当前分类、文档内活动数量和事件分组全量结果均为100%，第一期仍刻意不评测活动时效。
- 产品 UI 与内部复核 API 默认只监听 `127.0.0.1`；当前有完整本地产品页面，但仍没有账号体系或远程部署配置。
- 会籍策略 Agent 使用 v3 工作区、持久运行、独立工具及确定性等待检查。模型未配置时会明确报告不可用，知识、简报和完整图可独立浏览。真实模型验收应记录所用模型、工具输入输出及实际完成的场景。
