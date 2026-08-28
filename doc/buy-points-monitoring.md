# AwardWallet 买分/买里程优惠监控

## 边界

这条链路只读取以下唯一页面：

`https://awardwallet.com/news/current-promotions-buy-points-miles/`

来源 ID 是 `awardwallet_buy_points_page`，每天自动采集一次。`SinglePageAdapter` 每轮只发现同一个稳定条目，只请求配置的 canonical URL，并校验最终 URL 的 scheme、host 和 path。正文中的项目详情、affiliate 跳转和外部购买链接只作为结构化字段保存，不会在本链路中继续请求。

处理器是确定性 HTML 解析器，不创建或使用 `AIProvider`，也不占用模型调用预算。它与会籍文章、StatusMatch、FactSet、文章简报和会籍图分开；共享部分只有通用的 `Source`、`SourceItem`、`DocumentVersion`、`JobRun` 和每日自动化外壳。

## 采集、解析与存储

每轮都重新获取页面，内容不变时复用现有 `DocumentVersion`，内容变化时创建新版本。原始 HTML 保存在 `DocumentVersion.raw_body`，供结构解析；清洗后的正文仍可用于通用审计，但不会进入会籍 AI 链路。

解析器要求航空、酒店、其他交通三个主分区都存在，并从非表头 `.pt-row` 提取完整活动清单。三个主分区的实际有效行数是唯一活动数量；页面标题中的数字不参与提取或完整性判断。顶部 `tablepress-1310` 推荐表完全忽略，不匹配、不补充字段，也不会影响解析结果。缺分区、重复活动身份以及主表中的非空非法日期或百分比仍会 fail closed，不会写入半成品快照。

派生数据位于：

- `buy_points_snapshots`：一个 `DocumentVersion` 加 parser version 对应一个不可变解析快照，保存页面标题、更新时间、主表实际数量、集合签名和诊断。
- `buy_points_offers`：后台保存分类、项目名、完整优惠原文、bonus/discount、最大百分比、截止日、到账时间、详情/购买 URL、字段 evidence 和物料签名。正常读取隐藏重复的优惠原文和 evidence，并把购买入口输出为 `purchase_url`。

活动身份优先使用详情 URL 的 host/path，其次使用购买 URL 的 host/path，最后才使用分类与规范化项目名。因此优惠幅度、截止日或到账时间变化会产生 `CHANGED`，不会把同一活动误判为新活动。

## 当前状态与历史

“当前来源仍列出”与“截止日是否有效”是两个独立维度：

- `is_currently_listed`：活动是否仍在最新成功快照中。
- `deadline_status`：按 `Asia/Shanghai` 自然日计算 `ACTIVE | EXPIRED | UNKNOWN`。
- `source_stale`：来源仍列出但截止日已经过去。系统只报告诊断，不会擅自删除或改写来源清单。

采集或解析失败时，最新成功快照继续作为当前视图。历史 Diff 按稳定 `offer_key` 输出 `ADDED | CHANGED | REMOVED | UNCHANGED`。

## CLI

```bash
# 只采集
uv run journeyplus collect awardwallet_buy_points_page --limit 1

# 只处理待解析版本（零 AI）
uv run journeyplus process-buy-points --limit 10

# 采集后处理（零 AI，允许没有 AI 凭证）
uv run journeyplus run-source awardwallet_buy_points_page --limit 1

# 当前、历史和最近两个成功快照的 Diff
uv run journeyplus buy-points-current
uv run journeyplus buy-points-history --limit 20
uv run journeyplus buy-points-history --offer-key 'detail:awardwallet.com/...' --limit 20
uv run journeyplus buy-points-diff
uv run journeyplus buy-points-diff --before <snapshot-uuid> --after <snapshot-uuid>
```

所有读取命令输出 JSON。`automation-status` 中该来源的 `pending_document_count` 是缺少当前 parser version 快照的 `DocumentVersion` 数量；最近一轮摘要包含选择、成功、失败、复用、最新活动数和诊断。买分计数不计入任何 AI 分项。

## 页面改版排查

1. 查看 `SourceAutomationState.last_error`、失败的 `JobRun` 和 `automation-status` 中的积压；错误字段只保存安全摘要，不保存整页 HTML。
2. 用唯一真实 URL 做一次只读获取，把 HTML 保存到仓库外，核对三个 section ID、`.purchase-times--date` 和 `.pt-row`；标题数量及顶部推荐表不属于解析输入。
3. 先用新的最小固定 fixture 更新解析器测试，再提升 `BUY_POINTS_PARSER_VERSION`。旧 parser version 的快照会保留并存，不应原地改写。
4. 部署迁移和代码后运行 `process-buy-points`，确认新的成功快照成为当前视图；失败时旧成功视图仍然保留。

## 关闭调度与回滚

临时止血可以在数据库执行：

```sql
UPDATE sources
SET automatic_scheduling = false
WHERE id = 'awardwallet_buy_points_page';
```

再次执行 `seed-sources` 会按注册表恢复配置。需要持久关闭时，应同时把 `src/journeyplus/sources/registry.py` 中该来源的 `automatic_scheduling` 改为 `False`，运行测试后再播种来源。关闭调度不会删除 `DocumentVersion`、买分快照或历史活动。

迁移降级到 `0012_discovery_cursor` 只会删除 `buy_points_offers` 和 `buy_points_snapshots` 两张派生表；执行前应明确接受丢失买分历史。它不会删除来源、文档或会籍业务表。
