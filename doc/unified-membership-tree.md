# 统一会籍匹配树与普通文章映射生命周期

## 运行边界

统一树是一个只读投影，不是新的活动合并系统。它在查询时组合两类直接贡献：

- ACTIVE StatusMatch 项目当前官方 FactSet 中的映射；
- LoyaltyLobby 普通文章最新成功分析中、有逐字证据且当前可见的直接映射。

两条工作流不互相导入，也不修改对方的数据。只有
`UnifiedMembershipTreeService` 可以组合两个来源中立适配器。树构建、同边去重、循环检测和多跳展开
全部是确定性代码，不调用 AI，也不持久化传递边。当前仍不做跨文章召回、相似度、关系 AI、事件合并
或事实协调。

默认用户树不显示“官方/第三方”标签、贡献者列表、证据 provenance 或 180 天内部字段。同一对规范化
起止节点只显示一条边；管理员审计保留每个独立贡献及其原始证据、DocumentVersion、FactSet 或
ArticleOpportunity 和生命周期。

## 普通文章有效期

普通文章的直接映射在 `ArticleOpportunityRecord` 首次写入时确定可见截止：

1. 有明确申请截止时间：`EXPLICIT_DEADLINE`，以该时间为准；
2. 没有明确截止时间：`DEFAULT_180_DAYS`，以 `SourceItem.published_at + timedelta(days=180)` 为准；
3. 发布时间缺失：以 SourceItem 首次采集 `created_at + timedelta(days=180)` 为准。

第 180 天使用严格边界：`now < visibility_until_at` 才可见，
`now >= visibility_until_at` 立即从树中排除。180 天只是映射新鲜度，不会写进 FactSet 的 deadline，
也不会进入用户简报。重新抓取或重新解析同一个 SourceItem 不会重置起算时间；统一树只读取该
SourceItem 最新成功分析。

每日生命周期任务在边界到达后软归档贡献：明确截止写 `DEADLINE_EXPIRED`，默认 180 天写
`STALE_180D`。即使定时任务延迟，树的读取谓词仍会实时排除到期贡献。软归档不删除原文、事实、
简报或审核记录，也不替代普通文章原有的业务 lifecycle status。

人工操作均写入 `ReviewDecision` 的 before/after：

```bash
uv run journeyplus article-mapping-archive OPPORTUNITY_ID \
  --reason "活动已无法申请" --actor operator
uv run journeyplus article-mapping-restore OPPORTUNITY_ID \
  --reason "重新核实仍开放" --actor operator
uv run journeyplus article-mapping-extend OPPORTUNITY_ID 2027-03-01T00:00:00+08:00 \
  --reason "重新核实新的有效期" --actor operator
```

尚未到期的人工归档可直接恢复；已经到期时必须提供新的未来时间。延长或带新时间恢复会写
`MANUAL_OVERRIDE` 并清除归档字段。

## StatusMatch 关联文章

包含精确项目专属 `*.statusmatch.com` 链接的 LoyaltyLobby 文章继续走 StatusMatch 专用路由，
但现在只生成相对官方 FactSet/Brief 的 `highlights`：

- 不创建普通 ArticleAnalysis 或 ArticleOpportunity；
- 不生成或审批第三方映射 claim；
- 不进入统一树，也没有普通文章的 180 天映射字段；
- 不修改官方 FactSet、Brief、event、watch 或图；
- 相同 DocumentVersion、官方 FactSet、Brief、模型、提示词和 Schema 重跑为 0 次 AI 调用。

历史数据库中的 `candidate_status_mappings` 输入和 `mapping_claims` 列仅为读取兼容保留，当前输出、
CLI/API 和任何图服务都不消费它们。

## 查询与审计

```bash
# 用户视角：统一后的有界树
uv run journeyplus statusmatch-graph "ClubAvolta" "Gold"

# 管理员视角：统一贡献、排除原因和拓扑
uv run journeyplus membership-graph-audit

# 回归/审计视角：仅 StatusMatch 官方图
uv run journeyplus statusmatch-graph-audit
```

内部 API 的 `/internal/statusmatch/graph/tree` 返回统一用户树；
`/internal/membership/graph/audit` 返回统一管理员审计；
`/internal/statusmatch/graph/audit` 继续只审计官方 FactSet 图。

## 部署顺序

1. 先部署代码并执行 `uv run alembic upgrade head`，迁移到 `0011_mapping_visibility`；迁移只新增列、
   索引并回填，不删除历史数据。
2. 对比 `statusmatch-graph-audit` 的仅官方拓扑与变更前基线，确认官方 exact、conditional、wildcard、
   uncertain、多跳和循环语义不变。
3. 检查 `membership-graph-audit` 中普通文章贡献、证据及 excluded 统计。
4. 启用扩展后的每日生命周期任务，再将用户树入口切到统一投影。
5. 停止历史候选映射的人工入口；历史列和值保留。

短期业务回滚不需要降级数据库：把用户入口改回 `MembershipGraphService` 的仅官方树，并暂停普通文章
映射生命周期归档即可。不要删除 `0011` 字段或历史候选值。若必须做 schema downgrade，可执行
`uv run alembic downgrade 0010_generic_article_v2`；这会移除 `0011` 的四个新增字段和索引，但不会
删除 ArticleOpportunity、原文、事实或简报。再次升级会按原始截止/发布时间重新回填。

真实数据验收见 [2026-08-26 统一会籍树真实验收](unified-membership-tree-real-validation-2026-08-26.md)。
