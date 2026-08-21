# 会籍机会第一期冻结金标基线分析

## 运行身份与完整性

- 金标：`gold/status_opportunity_phase1_v1.json`
- 金标 SHA-256：`bd85babf9812533410c3e1f3c9a7e8d6265215c904aecfcebb89935811153605`，与冻结清单一致
- 数据集版本：1；文档 65 份，其中 `STATUS_OPPORTUNITY` 49 份、`NONE` 16 份
- 模型：`deepseek-v4-flash`，temperature 0，`json-mode-pydantic-v1`
- 分类提示词：`status-document-classification-v3`，Schema 2
- 关系提示词：`event-relationship-v1`，Schema 1
- 运行结果：65/65 完成；65 个分类结果、51 个模型关系结果全部成功；最终 `AnalysisRun` 失败数为 0
- 隔离：运行使用独立 SQLite 状态库，没有写入正式业务数据库
- 时间边界：本报告明确不评测申请开始、截止、生命周期或归档状态

本次曾在 17/65 后因 SQLite 新旧事件时间戳的时区表示不一致而中断。修复候选排序的时间标准化并增加回归测试后，从原缓存续跑完成。第二次调用复用了两个尚未提交到状态库但已经成功缓存的结构化结果。完整缓存最终包含 116 个有效结构化输出；第二次调用有 95 次模型请求，其中一次首次尝试未形成有效缓存、随后由分类器既有重试机制恢复，最终没有失败分析。

## 指标总览

| 指标 | 结果 |
|---|---:|
| 文档标签准确率 | 64/65 = 98.46% |
| `STATUS_OPPORTUNITY` Precision / Recall / F1 | 98.00% / 100.00% / 98.99% |
| `NONE` Precision / Recall / F1 | 100.00% / 93.75% / 96.77% |
| 文档内活动数完全匹配 | 60/65 = 92.31% |
| 事件提示总数 | 金标 52；预测 57 |
| 唯一事件组数 | 金标 44；预测 49 |
| Pairwise TP / FP / FN / TN | 5 / 4 / 10 / 1307 |
| Pairwise Precision / Recall / F1 | 55.56% / 33.33% / 41.67% |

标签混淆矩阵只有一个错误：一份金标 `NONE` 被判成 `STATUS_OPPORTUNITY`。49 份正例全部召回，没有正例漏判，也没有 `UNCERTAIN` 或最终结构化失败。

分类结果已经较稳定，但活动提示粒度和跨文章事件关系明显没有达到“低人工介入全自动聚合”的目标。Pairwise 指标中的 10 次误拆和 4 次误合是文档对数量，不代表 14 个独立模型根因；它们集中在少数活动族。

## 文档标签错误

### IHG 双倍精英房晚活动：`NONE` → `STATUS_OPPORTUNITY`

文档键：`frequentmiler_elite_status_feed:targeted-ihg-promo-earn-double-elite-night-credits-limit-10-bonus-elite-nights`

模型理由是“双倍精英房晚有助于加速积累会籍资格，属于直接的会籍机会”，并输出 `OTHER_DIRECT_STATUS`。这与金标规则冲突：精英房晚只是资格进度，不直接授予、升级或延长会籍。它同时构成唯一标签错误和一项活动数错误。

判断：分类边界错误，适合通过提示词负例或更明确的“直接结果”判据处理。

## 文档内活动数量错误

除 IHG 误判外，另有四份正例均为过度拆分，没有活动漏抽：

1. Flying Blue 截止报道，金标 1、预测 2。正文主体是 Flying Blue；模型把正文中“错过后可考虑 Vietnam Airlines Lotusmiles”的顺带替代链接也提取成独立活动。
2. Finnair Plus → Radisson Rewards 匹配，金标 1、预测 2。模型把 Premium 与 VIP 两档映射拆成两个提示；聚合器随后又把它们聚回同一个预测事件。因此这是分类提示粒度问题，不是最终数据库误拆。
3. GHA Discovery 付费匹配，金标 1、预测 2。模型把 Platinum 与 Titanium 两个价格档拆开；关系模型随后正确识别为同一活动并聚回一个事件，同样属于提示粒度问题。
4. Marriott Bonvoy 与 JAL 合作，金标 1、预测 2。模型把双向会籍路径拆成两个独立事件，关系模型认为方向相反而保持分离；金标把它们视为同一项合作活动。

判断：提示词目前只说明“每个彼此独立的机会输出一个提示”，尚未明确同一活动的多个目标等级、价格档、资格映射或双向合作是否仍为一个活动，也没有足够强调忽略主体活动中的顺带替代推荐。

## 跨文章事件分组

第一期金标只有四个事件在多篇文档中重复出现：

| 人工事件 | 文档数 | 预测组数 | 结果 |
|---|---:|---:|---|
| Kenya Airways Asante Rewards 付费匹配 | 5 | 2 | 误拆，产生 6 个 pairwise FN |
| Flying Blue 通用付费匹配 | 3 | 3 | 全部拆开，产生 3 个 pairwise FN |
| Alaska Atmos 企业挑战 | 2 | 2 | 误拆，产生 1 个 pairwise FN |
| Malaysia Airlines Enrich 付费匹配 | 2 | 1 | 正确聚合 |

也就是说，四个可检验的跨来源重复活动族中，只有 Malaysia Airlines 一个完整聚合正确。

### Kenya Airways 误拆

首篇 FFB、AwardWallet 和 FFB 汇总条目聚到 `predicted-event-001`；Frequent Miler 与很旅行聚到 `predicted-event-007`。后两篇使用 `Kenya Airways`、`STATUS_MATCH`，首篇使用 `Kenya Airways Asante Rewards`、`PAID_STATUS`。现有召回依赖项目名精确相等、机会类型相等、目标等级精确相等或全文查询，未把原事件送入关系模型，关系模型看到的是无关候选。

判断：主要是候选召回和项目/机会类型规范化问题，不是关系模型在看见正确候选后拒绝合并。

### Flying Blue 误拆并发生一次误合

三篇通用 Flying Blue 活动分别落入三个预测事件。项目名出现 `Air France KLM Flying Blue`、`法航荷航（Flying Blue）`、`Flying Blue`，机会类型出现 `DIRECT_STATUS_GRANT`、`STATUS_MATCH`、`PAID_STATUS`，导致正确事件没有稳定进入候选。

与此同时，英国 BA Club 专场先创建了一个独立事件。通用 FFB 条目含有 `OFFER UPDATED`，关系模型据此把通用活动错误判为英国专场的 `UPDATE_OF`，尽管两者资格范围不同。该错误产生 1 个 pairwise FP。

判断：同时存在召回规范化不足和关系判断过度依赖“updated”措辞两个问题。

### Alaska 企业挑战误拆

AwardWallet 使用 `Alaska Airlines Atmos Rewards` + `STATUS_CHALLENGE`，FFB 汇总条目使用 `Alaska Airlines` + `FAST_TRACK`。FFB 条目召回了同品牌的 San Diego 快速通道，但没有召回真正相同的企业挑战；关系模型正确拒绝了 San Diego 候选，却只能新建事件。

判断：也是候选召回问题；不能仅靠关系提示词修复一个从未进入候选列表的事件。

## 不同活动误合并

4 个 pairwise FP 来自两个根因：

1. KM Malta 条目被并入 Kenya Airways，产生 3 个 FP。冻结正文标题和申请链接指向 `KM Malta Airlines KM Rewards`，但正文句子错误写成 Kenya Airways；金标审核文件已经明确把它记录为来源笔误。分类模型选择了正文中的 Kenya Airways，关系模型随后以 0.95 置信度并入 Kenya 事件。这里不是普通的品牌相似，而是来源内部自相矛盾时系统没有转入 `UNCERTAIN / NEEDS_REVIEW`。
2. Flying Blue 英国 BA Club 专场与通用付费匹配被合并，产生 1 个 FP。两者同品牌但资格范围不同，通用条目中的 `OFFER UPDATED` 被错误解释成专场活动更新。

## 根因归类与建议决策

建议把后续候选修正分成四组，并继续使用同一份冻结金标比较，不制作第二版金标：

1. **分类边界**：明确精英房晚、定级积分等“只增加资格进度”的促销不是直接会籍机会。
2. **活动提示粒度**：明确正文主体中的顺带替代推荐应忽略；同一活动的多个等级/价格档/映射默认一个提示；双向合作是一个活动还是两个机会需按当前金标规则明确为一个提示。
3. **候选召回规范化**：解决品牌别名、忠诚度项目全称/简称、中文/英文名称和 `PAID_STATUS / STATUS_MATCH / FAST_TRACK / STATUS_CHALLENGE` 表达差异。该工作不需要新增业务结构化字段，但必须确保正确候选能进入关系模型。
4. **关系保守性**：同品牌不同资格范围不能因 `updated` 一词自动合并；标题、链接域名和正文品牌冲突时应保持独立并进入复核，而不是高置信度合并。

只调整分类提示词可以解决 1 个标签错误和大部分活动数过拆，但不会解决 Kenya、Flying Blue、Alaska 的召回误拆。只等待后续活动窗口也不够，因为这三类错误首先发生在品牌/项目名和机会类型表达不一致，正确候选根本没有进入关系判断。

基于本次结果，建议将文档分类视为基本可用，但暂不通过跨文章自动聚合验收。下一步应由用户确认上述四类修正的范围，再实现候选版本并用同一冻结集重跑比较；在确认之前不修改分类提示词、事件召回或关系规则，也不进入时效性阶段。
