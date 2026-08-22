# 人工金标

第一版金标使用 `GoldDataset` JSON Schema，覆盖文档单标签、文档内活动归属、事件关系或分组、关键事实和证据定位。文档标签只允许 `STATUS_OPPORTUNITY | NONE | UNCERTAIN`，不设上线阈值。

第一阶段冻结版为 `status_opportunity_phase1_v1.json`，已于 2026-08-21 经人工确认。它包含用户指定的 30 篇文章和 FFB 会籍列表的 35 个顶层条目，不包含 StatusMatcher；当前 `relationships` 和 `facts` 保持为空。

首轮真实基线后，人工确认三处标注策略需要纠正，因此另行冻结 `status_opportunity_phase1_v2.json`。v2 不重抓正文、不加入时效字段：两项 IHG 限时双倍精英房晚促销改为两个独立的 `STATUS_OPPORTUNITY`，Flying Blue 英国 BA Club 入口与通用入口归入同一现实活动。v1 保持不变，用于复现调整前结果。

第二次运行后另行冻结 `status_opportunity_phase1_v3.json`：iPrefer混合游记按用户决定改为 `NONE`，雅高混合文章改为“赠送等级房晚 + Kenya Airways匹配”两项会籍活动并排除五折房券。v3仍复用相同65份正文，马航文章继续保留Malaysia Airlines Enrich与Garuda Gold Privilege两项活动。

关系稳定性复核后另行冻结 `status_opportunity_phase1_v4.json`：Best Western Service Rewards 对美国和加拿大军人的 Gold 直授入口按用户决定归入同一现实活动。v4 仍复用相同65份正文，不改变任何标签或活动出现次数；Flying Blue 与 Malaysia Airlines 的人工活动键原本已合并，只由生产关系逻辑增加项目专属 `*.statusmatch.com` 子域强信号。

## 冻结规则

- `dataset_version` 为 `1`；指定文章案例版本为 `3`，FFB 列表案例版本为 `1`。
- `status_opportunity_phase1_v1.freeze.json` 保存冻结文件的 SHA-256、样本数量和边界声明。
- 禁止重新运行生成脚本覆盖 v1。标签、正文、活动归并或边界如需变化，必须创建新的数据集版本。
- v2 的 `dataset_version` 为 `2`；指定文章案例版本为 `4`，FFB 列表案例版本为 `2`。`scripts/revise_phase1_gold_v2.py` 只从已冻结 v1 确定性生成这三处纠错，并断言全部正文和 URL 不变。
- v3 的 `dataset_version` 为 `3`；指定文章案例版本为 `5`，FFB 列表案例版本仍为 `2`。`scripts/revise_phase1_gold_v3.py` 从冻结 v2 生成，并再次断言正文和 URL 不变。
- v4 的 `dataset_version` 为 `4`；指定文章案例版本仍为 `5`，FFB 列表案例版本为 `3`。`scripts/revise_phase1_gold_v4.py` 从冻结 v3 生成，只允许两个 Best Western 活动键发生已确认的归并，并断言全部正文和 URL 不变。

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

运行当前真实模型的冻结基线：

```bash
uv run journeyplus ai-smoke
uv run journeyplus-gold-run gold/status_opportunity_phase1_v1.json \
  --output-dir evaluation/runs/status_opportunity_phase1_v1-current
```

运行纠错与提示词/聚合调整后的第二次全量测试：

```bash
uv run journeyplus-gold-run gold/status_opportunity_phase1_v2.json \
  --output-dir evaluation/runs/status_opportunity_phase1_v2-candidate \
  --label candidate
```

运行 v3 人工边界纠错和关系加固后的最终全量验证：

```bash
uv run journeyplus-gold-run gold/status_opportunity_phase1_v3.json \
  --output-dir evaluation/runs/status_opportunity_phase1_v3-final \
  --label candidate-v3-final
```

运行 v4 关系稳定性规则和 Best Western 归并边界的全量验证：

```bash
uv run journeyplus-gold-run gold/status_opportunity_phase1_v4.json \
  --output-dir evaluation/runs/status_opportunity_phase1_v4-statusmatch-anchor-signal \
  --label candidate-v4-statusmatch-anchor-signal
```

运行器先校验冻结清单，再在输出目录内使用隔离 SQLite 数据库处理文档；不会写入正式数据库。输出包括 `current-output.json`、`report.json`、`cache.json`、`run.json` 和本地状态库 `state.sqlite`。同一模型、提示词和金标身份可直接重跑或中断续跑；身份变化时必须使用另一个输出目录，以保留旧基线用于比较。报告中的 `model_calls` 和 `cache_hits` 表示本次调用，`cached_outputs` 表示当前缓存累计保存的结构化输出数。`--max-documents N` 可用于有限文档测试。第一期报告只评测分类和事件分组，不评测时效。

每次修订案例时递增案例 `version`，整套集合发布时递增 `dataset_version`。
