# JourneyPlus

JourneyPlus 当前实现的是第一条纵向能力：从七组精选第三方来源发现“直接获得、升级或延长会籍”的机会，经轻量清洗、精确与语义去重、证据化事实整理后生成中文原创简报。

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
uv run journeyplus ai-smoke
uv run journeyplus gmail-authorize
uv run journeyplus review-api
```

自动化单元测试可以使用 SQLite；本地真实联调与生产配置使用 PostgreSQL。所有采集频率默认均为空，因此不会自动运行来源任务。外部来源只能通过手工命令或内部 API 触发。

本地 PostgreSQL 使用 Docker Compose，只绑定 `127.0.0.1`。当前默认端口为 `5433`，避免与其他本地项目的 PostgreSQL 冲突：

```bash
docker compose up -d --wait postgres
uv run alembic upgrade head
uv run journeyplus seed-sources
```

`collect` 只负责采集与精确去重，`process-pending` 只处理数据库中的待分析文档，`run-source` 是依次调用两者的薄编排。首次真实运行应使用 `--limit 1` 控制抓取量和模型费用。

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
8. 授权完成后可手工执行 `uv run journeyplus collect status_services_mail`。

OAuth 应用处于 Testing 状态时，External 测试用户授权通常会在 7 天后失效；第一轮验证可先保持 Testing，长期后台运行前再决定发布状态与 Google 验证方式。

### 公开来源只读冒烟

```bash
uv run python scripts/smoke_public_sources.py
```

该命令只验证六个无需账号的公开来源是否还能发现材料并取得首条正文，不写数据库、不调用 AI，也不测试 Gmail。

第一版流水线 OpenSpec 位于 `openspec/changes/build-status-opportunity-pipeline-v1/`；当前活动时效与自动化收尾契约位于 `openspec/changes/finish-status-opportunity-automation/`。

## 第一版已知限制

- 采集频率仍由用户决定，系统没有自动调度命令；每次只手工运行一个来源。
- 活动申请窗口、北京时间规范化、独立生命周期和过期软归档已经实现；生命周期单轮推进尚未接入每小时自动编排。
- Gmail 在首次部署时需要 Desktop OAuth 客户端 JSON 和浏览器授权；实现会安全保存并自动刷新只读令牌。
- 阿里云百炼真实调用需要北京地域 API Key；在配置密钥前仓库测试只使用结构化模拟响应。
- 本地真实联调与生产目标均使用 PostgreSQL；自动化单元测试继续使用 SQLite 兼容路径，并另外通过 Docker PostgreSQL 验证真实迁移与运行行为。
- 第一期65份冻结金标已完成 v4 最终确认；当前分类、文档内活动数量和事件分组全量结果均为100%，第一期仍刻意不评测活动时效。
- 内部复核 API 默认只监听 `127.0.0.1`，第一版没有公开 UI、账号体系或远程部署配置。
