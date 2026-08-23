# 会籍活动时效真实文章验证报告（2026-08-22）

## 结论

阶段四、阶段五在真实公开文章上的阻塞性时效问题已修复并通过复测。验证统一以北京时间 `Asia/Shanghai` 为查询和比较时区，覆盖明确延期、跨年度新一期、同品牌不同机制、仅日期、两位数年份、美国时区时刻、当前有效、已过期、缺少截止日以及截止证据冲突。

本轮没有改动冻结金标，也没有把第三方文章正文写入仓库；仓库只保存公开 URL、案例键和边界说明。所有代码和报告均保留在未提交工作区。

## 验证环境

- 日期与时区：2026-08-22，`Asia/Shanghai`
- 数据库：Docker PostgreSQL 17，使用隔离数据库 `journeyplus_real_lifecycle_20260822`、`journeyplus_real_lifecycle_fix_20260822`、`journeyplus_real_united_chain_20260822`、`journeyplus_real_timezone_20260822`
- 数据库迁移：在三个全新数据库中实跑 `0001 → 0002 → 0003`
- 模型：`aliyun-model-studio / deepseek-v4-flash`
- 模型配置：`cn-beijing:deepseek-v4-flash:temp-0:json-mode-pydantic-v1`
- 正文：运行时从公开网页或正式 Feed 获取并清洗；没有使用仓库内固定正文替代真实抓取

## 六个公开来源联调

每个来源先实际发现、抓取或读取 Feed 正文、清洗并受限处理一篇；随后用新采集运行键再次发现同一篇，六个来源都新增 `0` 个正文版本。

| 来源 | 实际发现数 | 首篇受限端到端结果 | 二次采集 |
| --- | ---: | --- | --- |
| FFB Elite Status Feed | 10 | Kenya Airways 付费匹配，`STATUS_OPPORTUNITY`，事件/事实/简报成功 | `new_versions=0` |
| FFB Status Match Catalog | 35 | Vietnam Airlines 匹配，`STATUS_OPPORTUNITY`，事件/事实/简报成功 | `new_versions=0` |
| AwardWallet Elite Status Feed | 10 | Hyatt Globalist 攻略，`NONE` | `new_versions=0` |
| LoyaltyLobby | 14 | Accor 早餐权益文章，`NONE` | `new_versions=0` |
| Frequent Miler Elite Status Feed | 20 | United Chicago 匹配，`STATUS_OPPORTUNITY`，事件/事实/简报成功 | `new_versions=0` |
| 很旅行 | 8 | 当前混合文章，`NONE` | `new_versions=0` |

## 人工阅读与真实文章边界矩阵

以下文章均人工打开并阅读了与申请期、挑战期、会籍有效期、延期或终止有关的正文，再与数据库事件、FactSet 证据和简报对照。

| 边界 | 真实材料 | 数据库结果 | 结论 |
| --- | --- | --- | --- |
| 两位数年份 + 明确延期 | [United 初始截止日](https://blog.frequentflyerbonuses.com/2025/01/january-17-2025-highlight.html)、[OFFER EXTENDED](https://blog.frequentflyerbonuses.com/2025/08/august-27-2025-highlight.html) | 同一事件 ID；第二篇为 `UPDATE_OF`、`deadline_extension=true`；截止日由 `Jun 30, 25` 更新为北京时间 2025-12-31 日末；当前 `EXPIRED` 且软归档 | 通过 |
| 同项目跨年度新一期 | [GHA 2025](https://blog.frequentflyerbonuses.com/2025/09/gha-discovery-status-match-2025.html)、[GHA 2026 首次回归](https://blog.frequentflyerbonuses.com/2026/03/gha-discovery-status-match.html) | 两个独立事件；截止日分别为 2025-11-30、2026-04-06 北京时间日末；均保持各自归档历史 | 通过 |
| 仅日期截止 | [Frontier Elite Gold](https://awardwallet.com/news/airlines/frontier-status-match/) | 2025-09-09 23:59:59.999999 北京时间，`EXPIRED` | 通过 |
| 同品牌不同机制 | [Frontier Platinum Challenge](https://awardwallet.com/news/airlines/frontier-elite-status-promotion/) | 与 Frontier Gold 拆分；文章顶部“已结束”与正文原截止日并存，截止事实冲突，按规范保守为 `UNKNOWN` | 通过 |
| 提前终止 + 原计划日期 | [JetBlue Dunkin](https://awardwallet.com/blog/jetblue-dunkin-status-promotion/) | 提前终止与原计划 9 月 1 日形成截止事实冲突，`UNKNOWN`，未误当作常驻机会 | 通过 |
| 重叠窗口但机制不同 | [JetBlue 25-for-25](https://awardwallet.com/news/jetblue-trueblue/25-for-25-challenge/) | 与 Dunkin、常驻匹配分别拆成三个事件；窗口为 2025-06-25 至 2025-12-31，`EXPIRED` | 通过 |
| 当前开放但无申请截止日 | [JetBlue 常驻 status match](https://awardwallet.com/airlines/jetblue-trueblue/jetblue-status-match/)、[Alaska Atmos Rewards](https://awardwallet.com/airlines/alaska-atmos-rewards/alaska-status-match/) | 挑战期和会籍有效期未被误用为申请截止日；均为 `UNKNOWN` | 通过 |
| 当前有效且有截止日 | [Delta 2026](https://awardwallet.com/airlines/delta-skymiles/delta-status-match/) | 截止日 2026-12-31 北京时间日末，`ACTIVE` | 通过 |
| 当前有效 + 数字短年份原文 | [United Chicago](https://frequentmiler.com/united-mileage-plus-status-match-promo-chicago/) | 与 2025 全国性活动拆分；截止日 2026-09-30 北京时间日末，`ACTIVE` | 通过 |
| 明确美国时区时刻 | [JetBlue Tiles 折扣](https://awardwallet.com/news/jetblue-trueblue/buy-jetblue-tiles/) | 原始事实 `May 28, 2026, 11:59 p.m. EST`；换算为 2026-05-29 12:59:00 北京时间，`EXPIRED` 且软归档 | 通过 |

没有在六个正式公开来源中找到一篇可信、已公告但截至 2026-08-22 尚未开始申请的活动，因此 `UPCOMING` 本轮只有确定性单元测试，没有伪造真实文章案例。当前仍在进行的 United Chicago 和 Delta 2026 已完成真实端到端验证。

## 实测发现并修复的问题

1. 两位数年份未解析：`9/30/26`、`Jun 30, 25`、`Dec 31, 25` 原来会使查询截止时间为空，并阻断明确延期关系。现已支持数字和英文月份的两位数年份。
2. 专属 `*.statusmatch.com` 子域误合并跨年度活动：GHA 正文明确写 `returned for the first time in 2026`，原来仍会被强制并入 2025 事件。现在明确新期次措辞和可靠非重叠窗口会绕过该强合并信号，交给关系判断并保持独立。
3. 常见美国时区文本未解析：模型从真实正文提取了 `11:59 p.m. EST on May 28, 2026` 和 `May 28, 2026, 11:59 p.m. EST` 两种格式，原实现均返回空。现在支持两种顺序及 `EST/EDT/ET`、`CST/CDT/CT`、`MST/MDT/MT`、`PST/PDT/PT`，并统一换算到北京时间。

## 幂等、迁移与自动化测试

- 12 个固定真实 URL 第二次采集全部为 `new_version=false`。
- 当前 Frequent Miler 同一采集幂等键第二次运行复用原 `run_id`，新增正文 0、待处理文档 0。
- 六个公开来源使用新的采集运行键再次发现首篇时，全部新增正文 0。
- `git diff --check`：通过。
- `python -m compileall`：通过。
- `pytest`：`126 passed`；有 1 条来自 FastAPI/Starlette 测试依赖的弃用警告，不影响本次结果。
- OpenSpec：`openspec validate finish-status-opportunity-automation --strict` 通过。
- `ruff`：项目未声明该依赖，本机环境不可调用，因此未执行且不记为通过。

## 运行可靠性观察

真实模型并非每次一次成功：四篇 FFB 首轮有两篇因简报引用校验失败，七篇 AwardWallet 首轮有一篇同类失败，失败事务人工重跑后全部成功；早先六源单篇联调中 Frequent Miler 也出现过事实结构校验抖动，重跑后成功。这些失败没有生成错误事件，但当前长批次缺少逐篇进度日志，失败文档也没有在同一单轮内自动重试。

因此，阶段四和阶段五的行为验收通过，OpenSpec 6.1 与 6.4 可完成；“无人值守可靠重试、进度与故障状态报告”仍属于阶段七 7.3、7.4，不应提前宣称完成。Gmail 真实三封邮件联调仍是 6.2、6.3，需要用户授权并提供可用的只读 OAuth 状态后执行。
