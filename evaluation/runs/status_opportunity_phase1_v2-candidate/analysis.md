# 会籍机会第一期 v2 第二次金标分析

## 结论

第二次全量运行完成，程序层面稳定：65/65 文档处理完成，104 次结构化模型调用全部成功，`AnalysisRun` 失败数为 0。核心聚合问题明显改善：Flying Blue 四份材料、Kenya Airways 五份材料和 Alaska 企业挑战两份材料都实际进入各自同一事件；KM Malta 不再误并入 Kenya；两项 IHG 精英房晚促销均被识别且保持独立；不同事件误合为 0。

仍不建议直接通过金标阶段门。剩余问题集中在三份很旅行文档：iPrefer 当前实测被漏判、雅高混合文章多抽两个活动、马航文章漏掉 Garuda Gold Privilege；此外马航中文文章与英文 FFB 条目仍因跨语言项目名没有召回而拆成两个事件。

## 运行身份与完整性

- 金标：`gold/status_opportunity_phase1_v2.json`
- 数据集版本：2；SHA-256：`6858c5a59d76262a2b356a3f8eb75b5e694eb67547c96fe6642ec0dd1a7599c2`
- 样本：65 份，`STATUS_OPPORTUNITY` 51 份、`NONE` 14 份；人工活动出现 54 次、唯一现实活动 45 个
- v2 沿用 v1 全部 URL 和规范正文，只修改两项 IHG 标签/活动键及 Flying Blue 英国入口归并键
- 模型：`deepseek-v4-flash`，temperature 0，`json-mode-pydantic-v1`
- 分类：`status-document-classification-v4`，Schema 3
- 关系：`event-relationship-v2`，Schema 1
- 输出：预测活动出现 54 次、唯一预测事件 46 个
- 运行：65/65 完成；65 个分类分析、39 个关系分析全部成功；模型调用 104，缓存命中 0
- 隔离：使用独立 SQLite 状态库，没有写入正式业务数据
- 本期仍不评测申请窗口、当前有效性、生命周期或归档

## 正式指标

| 指标 | 首轮 v1 报告 | 第二次 v2 报告 |
|---|---:|---:|
| 文档标签准确率 | 64/65 = 98.46% | 64/65 = 98.46% |
| `STATUS_OPPORTUNITY` Precision / Recall / F1 | 98.00% / 100.00% / 98.99% | 100.00% / 98.04% / 99.01% |
| 文档内活动数完全匹配 | 60/65 = 92.31% | 62/65 = 95.38% |
| Pairwise TP / FP / FN / TN | 5 / 4 / 10 / 1307 | 13 / 0 / 5 / 1413 |
| Pairwise Precision / Recall / F1 | 55.56% / 33.33% / 41.67% | 100.00% / 72.22% / 83.87% |

v1 与 v2 有三处人工标注变化，所以上表适合看整体趋势，不是完全同口径。把首轮预测和第二次预测都按 v2 重评后，首轮 Pairwise 为 66.67% / 33.33% / 44.44%，第二次仍为 100.00% / 72.22% / 83.87%；结论不变：误合已清零，召回和聚合显著改善。

## 已解决问题

### IHG 两项活动

- LoyaltyLobby 的最多 5 个额外精英房晚被正确识别为一个活动。
- Frequent Miler 的企业定向、最多 10 个额外精英房晚被正确识别为另一个活动。
- 关系模型读取到上限和窗口不同，返回 `DIFFERENT_EVENT`；两者分别为 `predicted-event-005` 和 `predicted-event-006`。

### FFB 权威项目名与 KM

FFB 条目左侧项目名进入受信上下文，并在结构化结果后再次确定性约束 `program`。KM 条目最终使用 `KM Malta Airlines KM Rewards`，进入独立的 `predicted-event-024`，没有产生任何与 Kenya 的误合。

### Flying Blue

以下四份材料全部进入 `predicted-event-002`：FFB 博客、很旅行 Flying Blue 提示、FFB 英国 BA Club 入口、FFB 通用入口。关系判断同时利用候选原始材料中的相同申请域名、费用、目标等级和有效期，没有再被 `OFFER UPDATED` 单独误导。正文顺带提到 Vietnam Airlines 也没有被另建提示。

### Alaska 与 Kenya

- Alaska 企业挑战的 AwardWallet 和 FFB 材料都进入 `predicted-event-003`；San Diego 快速通道和普通航司匹配分别保持为 `predicted-event-018`、`predicted-event-019`。
- Kenya 的 FFB 博客、AwardWallet、Frequent Miler、很旅行中的 Kenya 提示和 FFB 目录条目实际全部进入 `predicted-event-001`。

### 活动提示粒度

首轮过拆的三个边界均已修正：Finnair/Radisson 多等级为一个提示，GHA 多价格档为一个提示，Marriott/JAL 双向合作为一个提示。Flying Blue 主体文章也不再抽取顺带的 Vietnam Airlines。

## 剩余错误

### 1. iPrefer 当前实测被判为 NONE

文档：`verylvke_feed:2026:08:03:iprefer-titanium-status-match-scandic-avios`

模型认为文章以个人旅行攻略和经验分享为主，因此套用了“攻略文档为 NONE”的规则；但金标依据是正文给出了向 iPrefer 官方邮箱申请、附会籍截图并在一小时后成功获得钛金会籍的当前实测。这说明“主要目的”规则仍压过了“具体当前活动实测”规则。

建议后续明确：混合游记或攻略只要包含可复现的当前官方申请路径和成功结果，就应为该现实活动输出提示；纯长期教学才是 NONE。

### 2. 雅高混合文章多抽两个活动

文档：`verylvke_feed:2026:08:05:accor-all-plus-sale-kenya-airways-status-match`

金标只保留 Kenya 匹配，模型输出：

1. 欢悦卡促销送 5 个等级房晚；
2. 臻享卡免房券入住赠送五折房券；
3. Kenya Airways 会籍匹配。

第三个提示已经正确并入 `predicted-event-001`。第二个只是房券促销，属于明确误抽。第一个因为新版规则把“限时精英定级房晚”一般化为会籍机会，而 v2 金标只明确修改了两项 IHG，形成了尚未统一的产品边界：如果所有限时定级房晚促销都算会籍机会，金标也应把该雅高活动纳入；如果只在文章主体是定级促销时才算，则提示词需要加入主次限制。该点需要用户选择，当前未擅自继续修改。

正式 Pairwise 报告中的 4 个 Kenya `same_event_split` 都由此处的提示顺序造成：运行器按 hint index 将金标唯一的 Kenya 提示与预测第一个雅高提示对齐。语义复核确认真正的 Kenya 第三个提示已经与其他四份 Kenya 材料合并，不是关系模型再次拆分。

### 3. 马航文章少抽 Garuda Gold Privilege

文档：`verylvke_feed:2026:07:06:malaysia-airlines-status-match`

正文先报道 Malaysia Airlines Enrich 付费匹配，随后独立介绍 Garuda Indonesia Gold Privilege 的直接付费金卡。模型只输出马航提示，把 Garuda 当作马航资格背景。这是新版“同一活动多个等级/映射只输出一个提示”的反向过度合并；不同目标忠诚度项目且有独立行动链接，仍必须输出不同提示。

同时，中文提示 `马来西亚航空` 与 FFB 权威英文名 `Malaysia Airlines Enrich` 没有词面重叠，FFB 条目未召回中文既有事件，最终为 `predicted-event-014` 与 `predicted-event-025`。两份正文实际共享 `enrich.statusmatch.com`，后续可把材料中的行动链接域名作为临时召回信号，无需新增业务字段；召回后仍由关系模型决定，不直接合并。

## Pairwise 指标的语义复核

正式报告按同一文档内 hint index 对齐人工与预测提示，因此雅高文章的两个额外提示把真正 Kenya 提示挤到 index 2，产生 4 个表面 FN。按活动语义人工对齐后，四个重复活动族为：

| 人工活动 | 文档数 | 实际预测组数 | 结果 |
|---|---:|---:|---|
| Kenya Airways Asante Rewards | 5 | 1 | 完整聚合 |
| Flying Blue 通用活动 | 4 | 1 | 完整聚合 |
| Alaska Atmos 企业挑战 | 2 | 1 | 完整聚合 |
| Malaysia Airlines Enrich | 2 | 2 | 仍误拆 |

据此，语义复核的 Pairwise 为 TP 17、FP 0、FN 1、TN 1413，Precision 100%、Recall 94.44%、F1 97.14%。这是诊断用人工复核值，不替代运行器正式指标；正式指标仍保留对多抽活动的惩罚。

## 阶段判断

本轮已经达到“没有危险误合、核心重复活动大多能聚合”的水平，但还没有达到“可以低人工介入直接进入时效开发”的标准。建议先由用户决定雅高定级房晚的分类边界，再做一次很小的提示词/召回修正：修 iPrefer 当前实测、明确不同目标项目必须拆分、使用行动链接域名辅助跨语言召回，并同时改善多提示文档的评测对齐。此处按约定只报告，不继续修改验收类问题。
