# 每日自动化上线验收：2026-08-26

## 结论

2026-08-26 北京时间自然日的第一次真实 `run-daily` 单轮成功完成。两条当前来源均采集成功，来源游标均在成功事务中持久化；9 份通用文档全部处理成功，没有失败或剩余积压。LoyaltyLobby 新生成 1 个文章机会和 1 个简报，非空事实字段全部具有证据，没有重复机会键。StatusMatch 每日页面监控发现 1 个真实页面变化并按专用项目链路更新，没有来源故障。

本记录构成当前每日自动化的真实运行和上线验收证据。Codex 本地每日调度已在 2026-08-26 配置并完成同日幂等与来源隔离验证；用户确认以当前上线验收作为最终完成依据，因此本变更没有剩余完成门槛。

## 环境与运行前状态

- 数据库：本项目 Docker PostgreSQL 17，`localhost:5433/journeyplus`
- 迁移：真实升级 `0011_mapping_visibility → 0012_discovery_cursor`
- 北京时间日桶：`2026-08-26`
- 运行前今日来源采集：0 次
- 运行前今日自动单轮：0 次
- 运行前积压：3 份 LoyaltyLobby 文档
- 运行前历史失败任务：2 个
- 运行前 `NEEDS_REVIEW`：2 个
- 自动来源：仅 `loyaltylobby_feed` 与 `status_services_mail`

## 来源采集

| 来源 | 状态 | 发现 | 考虑 | 新文档版本 | 游标核对 |
| --- | --- | ---: | ---: | ---: | --- |
| `status_services_mail` | `SUCCEEDED` | 0 | 0 | 2 | 已保存数字 Gmail History ID；2 个版本来自本地旧快照解析版本补跑，不是新邮件正文下载 |
| `loyaltylobby_feed` | `SUCCEEDED` | 10 | 10 | 6 | 已保存 Feed GUID，且该 GUID 对应已入库 `SourceItem` |

LoyaltyLobby 本轮从 2026-08-24 全天基线之后追赶，完成后已切换为 Feed GUID 停止边界。两个来源均为连续失败 0、待处理 0。

## 外部调度与来源隔离

- Codex 本地自动化 `JourneyPlus 每日会籍采集`（ID `journeyplus`）已启用，每天本机时间 09:00 在保存的 JourneyPlus 项目中执行。
- 自动化使用本地项目目录，依次确保 Docker PostgreSQL 可用、升级迁移、执行不带来源参数的 `run-daily`，再执行 `automation-status`；不得修改代码、来源开关或 Git 历史。
- 正式 PostgreSQL 播种后核对八条现存来源记录：只有 `loyaltylobby_feed` 与 `status_services_mail` 同时为 `enabled=true`、`automatic_scheduling=true`、`collection_cadence=P1D`。
- `ffb_elite_status_feed`、`awardwallet_elite_status_feed`、`frequentmiler_elite_status_feed`、`verylvke_feed` 均为 `enabled=false`、`automatic_scheduling=false`；旧 `statusmatcher_reports`、`ffb_status_match_catalog` 同样双重关闭且采集周期为空。
- 安装后再次执行默认 `run-daily`：输出中只有当前两条来源，均复用 2026-08-26 已成功采集；新增处理 0、模型调用 0、StatusMatch 页面变化 0、积压 0，未触发任何关闭或退休来源。
- 来源注册、默认调度集合、关闭来源积压隔离、退休来源积压排除和同日日桶复用共 9 项自动化测试全部通过。

## 处理与调用预算

- 文档：选择 9、尝试 9、成功 9、失败 0、剩余积压 0
- 模型调用：7
  - 通用标题批次：1
  - 通用正文理解：3
  - 通用文章简报：1
  - StatusMatch 专用项目：2
  - 通用关系 AI：0
  - 通用二次事实 AI：0
  - StatusMatch 第三方补充：0
- 通用标题筛除：6
- 通用正文处理：3
- 新文章机会：1
- 新文章简报：1
- 生命周期：扫描 17、更新 0、过期 0；新文章机会为 `ACTIVE`

## StatusMatch 页面变化

- 检查项目：8
- 检查页面：16
- 变化页面：1
- 页面错误：0
- 归档项目：0
- 重新处理项目：1，成功 1，失败 0

Flying Blue FAQ 的公开内容变化触发专用项目重算。新结果增加英国和希腊申请路径，并继续保留阿根廷、巴西、智利 Platinum 可申请性矛盾为冲突；系统没有静默裁决，当前 `NEEDS_REVIEW` 总数仍为 2。

## 运行审计

- 新文章机会键重复组：0
- 新文章机会：1；新文章简报：1
- 所有非空事实字段均有证据，每字段证据数为 1–3
- 无证据的非空事实字段：0
- 通用关系/二次事实模型调用：0
- 本轮只有 1 个文章机会，没有跨机会串线
- 来源故障：0
- 处理失败：0
- 历史失败任务仍为运行前已有的 2 个，本轮没有新增

## 完成结论

1. 外部每日调度已启用，默认来源集合、关闭来源隔离和同日幂等均已验证。
2. 后续运行继续作为常规运维记录，不再构成本变更的额外完成门槛。
3. `finish-status-opportunity-automation` 变更宣布完成。
