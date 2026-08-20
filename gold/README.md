# 人工金标

第一版金标使用 `GoldDataset` JSON Schema，覆盖文档单标签、文档内活动归属、事件关系或分组、关键事实和证据定位。文档标签只允许 `STATUS_OPPORTUNITY | NONE | UNCERTAIN`，不设上线阈值。

当前第一阶段草稿为 `status_opportunity_phase1_v1.json`，包含用户指定的 30 篇文章和 FFB 会籍列表的 35 个顶层条目，不包含 StatusMatcher。人工审核入口为 `status_opportunity_phase1_v1_review.md`。在用户确认审核结果前，不使用这份草稿运行测评；当前 `relationships` 和 `facts` 保持为空。

对比已经导出的当前与候选结果：

```bash
uv run journeyplus-eval gold.json \
  --prediction current=current-output.json \
  --prediction candidate=candidate-output.json
```

每次修订案例时递增案例 `version`，整套集合发布时递增 `dataset_version`。
