# JourneyPlus

JourneyPlus 当前实现的是第一条纵向能力：从八组精选第三方来源发现“直接获得、升级或延长会籍”的机会，经轻量清洗、精确与语义去重、证据化事实整理后生成中文原创简报。

第一版明确不处理买分、转分、信用卡、积分票或积分房晚等独立主题，也不包含个人资产、推荐、通知和自动报名。

## 本地开发

```bash
uv sync --extra dev
uv run alembic upgrade head
uv run pytest
uv run journeyplus seed-sources
uv run journeyplus collect ffb_elite_status_feed
uv run journeyplus review-api
```

本地与测试可以使用 SQLite；生产配置使用 PostgreSQL。所有采集频率默认均为空，因此不会自动运行来源任务。外部来源只能通过手工命令或内部 API 触发。`statusmatcher_reports` 须在人工访问合规确认后显式增加 `--allow-statusmatcher`；邮件来源须配置只读 Access Token。

## 配置

复制 `.env.example` 中的变量到服务端运行环境。不要把 API Key、Gmail Access Token 或 Refresh Token 写入仓库。

OpenSpec 实施契约位于 `openspec/changes/build-status-opportunity-pipeline-v1/`。

## 第一版已知限制

- 采集频率仍由用户决定，系统没有自动调度命令；每次只手工运行一个来源。
- Gmail 尚需用户完成 Google OAuth 只读授权并注入 Access Token；适配器不会刷新或保存令牌。
- StatusMatcher 正式采集仍需人工完成访问与保存范围确认，未显式确认时适配器会拒绝运行。
- 阿里云百炼真实调用需要北京业务空间 Base URL 与同地域 API Key；仓库测试只使用结构化模拟响应。
- 生产目标是 PostgreSQL；本机没有 PostgreSQL 服务，因此当前自动化测试使用 SQLite 兼容路径，并由迁移测试验证完整表结构。
- 首批人工金标要等用户提供文章后共同建立；离线评测刻意不预设上线阈值。
- 内部复核 API 默认只监听 `127.0.0.1`，第一版没有公开 UI、账号体系或远程部署配置。
