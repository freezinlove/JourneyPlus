# 人工金标

第一版金标使用 `GoldDataset` JSON Schema，覆盖文档单标签、文档内活动归属、事件关系或分组、关键事实和证据定位。文档标签只允许 `STATUS_OPPORTUNITY | NONE | UNCERTAIN`，不设上线阈值。

当前第一阶段草稿为 `status_opportunity_phase1_v1.json`，包含用户指定的 30 篇文章和 FFB 会籍列表的 35 个顶层条目，不包含 StatusMatcher。在用户确认审核结果前，不使用这份草稿运行测评；当前 `relationships` 和 `facts` 保持为空。

审核文件分工：

- `status_opportunity_phase1_v1_review.md`：标签、活动拆分/归并和审核顺序。
- `status_opportunity_phase1_v1_bodies.md`：65份规范正文全文，按 `A01-A30` 和 `F01-F35` 编号。
- `status_opportunity_phase1_v1_bodies_zh.md`：对应的中文机器翻译阅读版，仅供人工审核，不写回金标证据正文。
- `status_opportunity_phase1_v1_extraction_audit.md`：各来源清洗前后字符数、最终保留链接、规则丢弃链接和残留异常检查。

正文清洗使用 `source-cleaner-v2`：FFB博客和AwardWallet从固定文章容器提取；LoyaltyLobby、Frequent Miler和VERYLVKE只使用Feed正文；FFB列表按顶层条目提取并保留有效链接。正文容器失效时直接报错，不回退到整页文本。

对比已经导出的当前与候选结果：

```bash
uv run journeyplus-eval gold.json \
  --prediction current=current-output.json \
  --prediction candidate=candidate-output.json
```

每次修订案例时递增案例 `version`，整套集合发布时递增 `dataset_version`。
