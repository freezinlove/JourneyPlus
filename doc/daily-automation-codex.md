# JourneyPlus 每日自动化（Codex）

## 当前配置

- 自动化名称：`JourneyPlus 每日会籍采集`
- 自动化 ID：`journeyplus`
- 宿主：Codex 本地任务，直接使用保存的 JourneyPlus 项目
- 计划：每天本机时间 13:00；当前本机时区为 `CST +0800`
- 执行环境：本地项目目录，不创建隔离 worktree
- 状态：`ACTIVE`

自动化每轮按以下顺序执行：

1. 读取并遵守项目 `AGENTS.md`。
2. 执行一次 `uv run journeyplus automation-status`，保存运行前基线。
3. 确保本项目 Docker PostgreSQL 可用。
4. 执行 `uv run alembic upgrade head`。
5. 执行不带来源参数的 `uv run journeyplus run-daily`。
6. 再次执行 `uv run journeyplus automation-status`，以数据库最终状态为准，并将本轮新增问题与历史遗留问题分开报告。

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

## 反馈约定

每日反馈面向非技术用户，必须先明确回答“今天是否成功”，不得用“本轮已完成”概括一个实际失败的运行，也不得同时报告互相矛盾的 `RUNNING` 与 `FAILED` 状态。

反馈依次说明：

1. 今天从三个正常来源分别获取了什么；0 条表示没有发现新内容，不自动视为故障。
2. 本轮新发生的具体问题、原因和业务影响；不得只写“解析失败”等内部术语。
3. 仍需处理的历史问题；失败记录必须区分本轮新增和以前遗留，并说明是否仍影响当前数据。
4. 需要人工确认的来源冲突；必须列出项目名及冲突双方，不得只报告“待复核”数量。
5. 最多三条按优先级排序的下一步建议。

常用内部术语应改写为：

- “积压”改为“尚未处理成功的材料”，并指出具体材料及未完成原因。
- “失败作业”改为“处理失败记录”，并标明发生日期、本轮新增或历史遗留、当前影响。
- “待复核”改为“来源说法冲突，需人工确认”，并列出冲突内容。
- “解析失败”改为“页面已获取，但程序没能从页面结构中可靠读出所需数据”，再补充具体未匹配内容。

模型调用次数仅作为末尾技术信息；除非调用本身失败，否则不作为故障项。

## 运维

在 Codex 自动化页面中按名称 `JourneyPlus 每日会籍采集` 查看最近运行、暂停、恢复或修改时间。变更时间或执行内容时应更新已有自动化，不要创建同名重复任务。

每天的运行结果由独立本地任务保存；业务状态可在项目中用以下命令复核：

```bash
uv run journeyplus automation-status
```
