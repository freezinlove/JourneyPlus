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
```

本地与测试可以使用 SQLite；生产配置使用 PostgreSQL。所有采集频率默认均为空，因此不会自动运行来源任务。外部来源只能通过手工命令或内部 API 触发。`statusmatcher_reports` 须在人工访问合规确认后显式增加 `--allow-statusmatcher`；邮件来源须配置只读 Access Token。

## 配置

复制 `.env.example` 中的变量到服务端运行环境。不要把 API Key、Gmail Access Token 或 Refresh Token 写入仓库。

OpenSpec 实施契约位于 `openspec/changes/build-status-opportunity-pipeline-v1/`。
