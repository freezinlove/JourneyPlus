# 人工金标

第一版金标使用 `GoldDataset` JSON Schema，覆盖文档单标签、文档内活动归属、事件关系或分组、关键事实和证据定位。文档标签只允许 `STATUS_OPPORTUNITY | NONE | UNCERTAIN`，不设上线阈值。

第一阶段冻结版为 `status_opportunity_phase1_v1.json`，已于 2026-08-21 经人工确认。它包含用户指定的 30 篇文章和 FFB 会籍列表的 35 个顶层条目，不包含 StatusMatcher；当前 `relationships` 和 `facts` 保持为空。

## 冻结规则

- `dataset_version` 为 `1`；指定文章案例版本为 `3`，FFB 列表案例版本为 `1`。
- `status_opportunity_phase1_v1.freeze.json` 保存冻结文件的 SHA-256、样本数量和边界声明。
- 禁止重新运行生成脚本覆盖 v1。标签、正文、活动归并或边界如需变化，必须创建新的数据集版本。

## 时间边界

本阶段金标不考虑活动是否仍然有效。标签回答的是“正文是否描述具体的会籍获取机会”，不是“用户现在是否还能参加”：

- 已截止或后来失效的活动仍可标为 `STATUS_OPPORTUNITY`。
- 文章发布时间、申请截止时间和会籍有效期不改变本阶段标签。
- 截止时间抽取、当前有效性筛选、活动过期状态和数据库归档属于后续独立能力，不纳入本数据集的标签、`relationships` 或 `facts`。
- 后续实现应将活动生命周期与现有审核状态分开记录；`StatusEvent.status` 当前用于 `DRAFT / NEEDS_REVIEW / CONFIRMED / MERGED` 等审核流程，不应直接复用为活动的时间状态。

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
