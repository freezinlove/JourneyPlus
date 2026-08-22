# 第一期人工金标 v2 纠错说明

本版是 `status_opportunity_phase1_v1.json` 的人工确认纠错修订，不是包含时效性的第二期金标。65 份 `source_url` 和 `normalized_body` 全部原样复用，v1 及其冻结清单继续保留用于首轮基线复现。

## 变更

| 文档 | v1 | v2 | 原因 |
|---|---|---|---|
| [IHG 双倍精英房晚，最多5晚](https://loyaltylobby.com/2026/08/08/update-ihg-one-rewards-double-elite-night-credits-august-5-september-29-2026/) | `NONE` | `STATUS_OPPORTUNITY`，独立活动 | 限时奖励会籍定级房晚属于会籍机会；本活动上限5晚，8月5日至9月29日。 |
| [IHG 企业定向双倍精英房晚，最多10晚](https://frequentmiler.com/targeted-ihg-promo-earn-double-elite-night-credits-limit-10-bonus-elite-nights/) | `NONE` | `STATUS_OPPORTUNITY`，独立活动 | 同样属于会籍机会，但企业定向、上限10晚且活动窗口不同，不与上一项合并。 |
| [Flying Blue 英国 BA Club 入口](https://www.frequentflyerbonuses.com/statusmatchoffers.html) | 独立英国活动键 | `flying-blue-paid-status-match-2026` | 人工核对后确认英国入口和通用入口指向同一现实活动。 |

Flying Blue 文章中顺带提到 Vietnam Airlines 的现有标注暂不调整。活动是否仍然有效、开始/截止时间抽取、生命周期和归档仍不属于本期金标。

## 汇总

| 标签 | 数量 |
|---|---:|
| `STATUS_OPPORTUNITY` | 51 |
| `NONE` | 14 |
| `UNCERTAIN` | 0 |
| 合计 | 65 |

完整正文继续查阅 v1 的 `status_opportunity_phase1_v1_bodies.md`；v2 的独立冻结清单保证任何后续变化都会在模型调用前失败。
