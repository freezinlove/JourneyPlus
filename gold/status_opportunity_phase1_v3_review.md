# 第一期人工金标 v3 纠错说明

本版继续复用 v1/v2 的全部65份 URL 与规范正文，不加入时效字段，只记录第二次运行后用户确认的最终分类边界。

| 文档 | v2 | v3 | 原因 |
|---|---|---|---|
| [iPrefer钛金匹配与Scandic兑换实战](https://www.verylvke.com/2026/08/03/iprefer-titanium-status-match-scandic-avios/) | `STATUS_OPPORTUNITY`，1项 | `NONE` | 用户确认该混合游记价值较低，本期不纳入。 |
| [雅高臻享卡促销与肯尼亚航空匹配](https://www.verylvke.com/2026/08/05/accor-all-plus-sale-kenya-airways-status-match/) | `STATUS_OPPORTUNITY`，仅Kenya | `STATUS_OPPORTUNITY`，2项 | 赠送5个等级房晚与Kenya匹配均属于会籍机会；五折房券不是会籍机会。 |

马航文章在 v2 已正确标注两项活动，无需修改金标：Malaysia Airlines Enrich付费匹配与Garuda Gold Privilege付费金卡必须拆分。v3 汇总为50份 `STATUS_OPPORTUNITY`、15份 `NONE`、0份 `UNCERTAIN`；人工活动出现54次、唯一现实活动45个。

## 最终全量验证

2026-08-21 使用 `status-document-classification-v6`、`event-relationship-v3` 和 `deepseek-v4-flash` 对同一份冻结 v3 做了最终 65 篇全量验证，结果保存在 `evaluation/runs/status_opportunity_phase1_v3-final/`：

- 65/65 文档完成，90 次模型调用，0 次分析失败；
- 文档标签 64/65，准确率 98.46%；
- `STATUS_OPPORTUNITY` Precision 100%、Recall 98%、F1 98.99%；
- 事件 pairwise 分组 TP 18、FP 0、FN 0、TN 1413，Precision/Recall/F1 均为 100%；
- KM Malta 与 Kenya Airways 保持拆分，Malaysia Airlines 中英文材料正确聚合，Garuda Gold Privilege 保持独立，Flying Blue 两个入口正确聚合，Best Western 美国与加拿大军人活动保持拆分；
- 唯一剩余错误是“八大洲一住升金”被模型判为 `NONE`：模型认为八大洲是普通旅行预订平台而不是旅行忠诚度项目。

2026-08-22 用户确认采用通用边界：旅行预订、旅行顾问或旅行会员平台通过具体活动直接授予或升级到明确命名的持续精英等级时，属于会籍机会；只有普通会员产品名称或购买后获得券、折扣、权益包而没有明确精英等级或定级进度时，仍为 `NONE`。该规则不得以“八大洲”专名白名单实现。

## 平台精英等级通用规则回归

`status-document-classification-v9` 在提示词中实现上述通用边界，并对“个人客服邮件成功 + 第三方数据点 + 无其他外部官方入口”的模型正判增加确定性公开性守卫。守卫不包含 iPrefer 或八大洲专名；具有官方群体活动入口的邮件申请仍保留为会籍机会。

2026-08-22 使用同一 v3 冻结文件完成 65 篇全量回归，结果保存在 `evaluation/runs/status_opportunity_phase1_v3-platform-rule-v9-full/`：

- 65/65 文档完成，92 次模型调用，0 次分析失败；
- 文档标签和文档内活动数量均为 65/65，`STATUS_OPPORTUNITY` 与 `NONE` 的 Precision、Recall、F1 均为 100%；
- 八大洲“一住升金”稳定识别为会籍机会，Accor Plus 买会员送券和 iPrefer 个人邮件数据点均为 `NONE`；
- 本轮关系模型出现 6 个应合并未合并和 1 个误合并，pairwise Precision 92.31%、Recall 66.67%、F1 77.42%。错误集中于 Flying Blue、Malaysia Airlines 跨材料聚合和 Best Western 美国/加拿大军人活动拆分；同一关系代码在 v6 全量运行曾达到 100%，因此记录为关系模型稳定性问题，不归因于本次分类规则；
- 金标阶段门继续保持未确认，直到关系判断波动另行处理并由用户确认。

> 后续人工复核已在 v4 中确认 Best Western 美国与加拿大军人入口应合并；本文件保留的是 v3 当时边界与运行记录，当前边界及修复结果以 `status_opportunity_phase1_v4_review.md` 为准。
