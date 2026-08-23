# JourneyPlus

JourneyPlus 当前实现的是第一条纵向能力：从六组精选第三方来源发现“直接获得、升级或延长会籍”的机会，经轻量清洗、精确与语义去重、证据化事实整理后生成中文原创简报。

第一版明确只处理会籍机会，文档标签只有 `STATUS_OPPORTUNITY | NONE | UNCERTAIN`。一篇文档只有一个标签，但可包含多个会籍活动。第一版不处理买分、转分、积分票或积分房晚，项目不建设信用卡独立主题；信用卡只能作为会籍机会的资格条件出现。第一版也不包含个人资产、推荐、通知和自动报名。

## 本地开发

```bash
uv sync --extra dev
uv run alembic upgrade head
uv run pytest
uv run journeyplus seed-sources
uv run journeyplus collect ffb_elite_status_feed --limit 1
uv run journeyplus process-pending --source-id ffb_elite_status_feed --limit 1
uv run journeyplus run-source ffb_elite_status_feed --limit 1
uv run journeyplus run-daily
uv run journeyplus automation-status
uv run journeyplus initialize-mail-details
uv run journeyplus initialize-window --start 2026-07-15 --end 2026-07-16
uv run journeyplus ai-smoke
uv run journeyplus gmail-authorize
uv run journeyplus review-api
```

自动化单元测试可以使用 SQLite；本地真实联调与生产配置使用 PostgreSQL。六组来源都已配置 `P1D`（每天一次），但初始化逐批审核完成前 `automatic_scheduling` 保持关闭，因此不会自行运行来源任务，也尚未安装外部定时任务。

本地 PostgreSQL 使用 Docker Compose，只绑定 `127.0.0.1`。当前默认端口为 `5433`，避免与其他本地项目的 PostgreSQL 冲突：

```bash
docker compose up -d --wait postgres
uv run alembic upgrade head
uv run journeyplus seed-sources
```

`collect` 只负责采集与精确去重，`process-pending` 只处理数据库中的待分析文档，`run-source` 是依次调用两者的薄编排。`run-daily` 是供未来外部定时器调用的单轮命令：它使用数据库租约和北京时间自然日幂等键，隔离来源失败，在上限内处理积压并推进生命周期。`automation-status` 显示租约、来源最后成功/失败、连续失败、积压、分析失败和待复核数量。当前自动标志关闭时，`run-daily` 不采集来源，但显式调用仍会处理既有积压并推进生命周期。

`initialize-mail-details` 从当前合规 Gmail 邮件中发现并去重项目专属 StatusMatch 链接，读取每个项目的活动首页与 `/faq`，完成处理后等待逐页原文审核。`initialize-window` 只接受从 `2026-07-15` 到 `2026-08-22` 的固定两日窗口（最后一批为单日）；五个公开 Feed 会自动翻页直到覆盖窗口起点。每批成功后状态停在 `AWAITING_AUDIT`，前一批原文审核没有显式通过时，下一批会被数据库阶段门拒绝；命令本身不会连续推进多个批次。

默认单轮上限可通过环境变量调整：

```bash
JOURNEYPLUS_AUTOMATION_SOURCE_ITEM_LIMIT=100
JOURNEYPLUS_AUTOMATION_DOCUMENT_LIMIT=20
JOURNEYPLUS_AUTOMATION_MODEL_CALL_LIMIT=100
JOURNEYPLUS_AUTOMATION_LEASE_SECONDS=3600
```

## 配置

复制 `.env.example` 为 `.env` 后填写服务端配置；程序会自动读取该文件。不要把 API Key、Gmail Access Token、Refresh Token 或 Google OAuth 客户端 JSON 写入仓库。

### 千问 AI 平台

第一版默认使用北京按量付费 OpenAI-compatible 地址 `https://dashscope.aliyuncs.com/compatible-mode/v1` 和 `deepseek-v4-flash`。只需在 `.env` 填写北京地域创建的 `JOURNEYPLUS_AI_API_KEY`，然后执行：

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
8. 授权完成后可手工执行 `uv run journeyplus collect status_services_mail`。适配器会检查邮件中的文字、按钮和图片链接，本地解开 StatusMatch 跟踪包装，只访问去重后的项目专属 HTTPS 活动首页与 `/faq`；不会请求包含收件人参数的跟踪中转地址。

本项目的 OAuth Audience 已在 2026-08-23 确认为 Production，当前只读刷新令牌已通过四封合规邮件的发现、清洗、完整分析和重复采集验证。若以后重新创建 OAuth 项目，Testing 状态的 External 测试用户授权可能较快失效，长期自动运行前仍须重新确认发布状态和刷新令牌。

### 公开来源只读冒烟

```bash
uv run python scripts/smoke_public_sources.py
```

该命令只验证五个无需账号的公开来源是否还能发现材料并取得首条正文，不写数据库、不调用 AI，也不测试 Gmail。

第一版流水线 OpenSpec 位于 `openspec/changes/build-status-opportunity-pipeline-v1/`；当前活动时效与自动化收尾契约位于 `openspec/changes/finish-status-opportunity-automation/`。

## 第一版已知限制

- 每日单轮命令、数据库租约、北京时间日桶、限额、故障隔离和状态报告已经实现；Gmail 详情页与受控历史初始化全部审核通过前不会安装外部定时任务，也不会打开六组来源的自动标志。
- 活动申请窗口、北京时间规范化、独立生命周期和过期软归档已接入每日单轮编排。
- Gmail 在首次部署时需要 Desktop OAuth 客户端 JSON 和浏览器授权；实现会安全保存并自动刷新只读令牌。
- 阿里云百炼真实调用需要北京地域 API Key；在配置密钥前仓库测试只使用结构化模拟响应。
- 本地真实联调与生产目标均使用 PostgreSQL；自动化单元测试继续使用 SQLite 兼容路径，并另外通过 Docker PostgreSQL 验证真实迁移与运行行为。
- 第一期65份冻结金标已完成 v4 最终确认；当前分类、文档内活动数量和事件分组全量结果均为100%，第一期仍刻意不评测活动时效。
- 内部复核 API 默认只监听 `127.0.0.1`，第一版没有公开 UI、账号体系或远程部署配置。
