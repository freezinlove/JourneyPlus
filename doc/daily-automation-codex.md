# JourneyPlus 每日自动化（Codex）

## 当前配置

- 自动化名称：`JourneyPlus 每日会籍采集`
- 自动化 ID：`journeyplus`
- 宿主：Codex 本地任务，直接使用保存的 JourneyPlus 项目
- 计划：每天本机时间 09:00；安装时本机时区为 `CST +0800`
- 执行环境：本地项目目录，不创建隔离 worktree
- 状态：`ACTIVE`

自动化每轮按以下顺序执行：

1. 读取并遵守项目 `AGENTS.md`。
2. 确保本项目 Docker PostgreSQL 可用。
3. 执行 `uv run alembic upgrade head`。
4. 执行不带来源参数的 `uv run journeyplus run-daily`。
5. 执行 `uv run journeyplus automation-status` 并报告来源、文档、机会、简报、StatusMatch、模型调用、积压、失败和待复核统计。

自动化不得修改代码、OpenSpec、来源开关或 Git 历史，也不得创建提交。`run-daily` 自身继续使用数据库租约和北京时间自然日幂等键；同一天重复触发时不会重复处理已成功来源。

## 来源边界

默认单轮不传入来源参数，只读取数据库中同时满足 `enabled=true`、`automatic_scheduling=true` 且配置采集周期的来源。当前注册表和播种结果仅允许：

- `loyaltylobby_feed`
- `status_services_mail`
- `awardwallet_buy_points_page`（固定单页、确定性结构解析、零 AI）

以下公开来源保留适配器与历史数据，但 `enabled=false`、`automatic_scheduling=false`：

- `ffb_elite_status_feed`
- `awardwallet_elite_status_feed`
- `frequentmiler_elite_status_feed`
- `verylvke_feed`

旧 `statusmatcher_reports` 和 `ffb_status_match_catalog` 在播种时会被强制关闭、清空采集周期，且不在正式注册表和 CLI 来源范围内。自动化提示同时明确禁止定向运行或启用这些关闭/旧来源。

## 运维

在 Codex 自动化页面中按名称 `JourneyPlus 每日会籍采集` 查看最近运行、暂停、恢复或修改时间。变更时间或执行内容时应更新已有自动化，不要创建同名重复任务。

每天的运行结果由独立本地任务保存；业务状态可在项目中用以下命令复核：

```bash
uv run journeyplus automation-status
```
