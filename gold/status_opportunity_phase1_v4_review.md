# 第一期人工金标 v4 关系纠错说明

本版继续复用 v1–v3 的全部65份 URL 与规范正文，不加入实效字段，也不改变任何文档标签或文档内活动数量。唯一人工边界调整是把 Best Western Service Rewards 对美国和加拿大军人的 Gold 直授入口归为同一现实活动。

| 文档 | v3 | v4 | 原因 |
|---|---|---|---|
| FFB：Best Western 美国军人 Gold 直授 | `best-western-us-military-gold-direct-grant` | `best-western-service-rewards-military-gold-direct-grant` | 同一 Best Western Service Rewards 计划和 Gold 直授机制，仅资格国家与注册链接不同。 |
| FFB：Best Western 加拿大军人 Gold 直授 | `best-western-canada-military-gold-direct-grant` | `best-western-service-rewards-military-gold-direct-grant` | 与美国入口属于同一现实活动。 |

v4 仍为50份 `STATUS_OPPORTUNITY`、15份 `NONE`、0份 `UNCERTAIN`；人工活动出现54次，唯一现实活动由45个调整为44个。Flying Blue 各入口和 Malaysia Airlines Enrich 中英文材料本来已使用同一人工活动键，本版不再改它们的金标，只用生产关系逻辑的通用规则消除运行波动。

## 关系规则

- 相同且能与双方项目身份对应的项目专属 `*.statusmatch.com` 子域是强关系信号；路径、查询参数和地区入口不同本身不拆分。
- 同一篇文章包含多个活动时，子域只能归属于项目身份匹配的活动，不能跨提示串线。
- `kmrewards.statusmatch.com` 与 `kenya-airways.statusmatch.com` 等不同项目子域保持分离。
- 后续加入活动窗口后，非重叠的新一期窗口优先于历史子域复用，仍须创建新事件。

## 两次全量运行

第一次使用 `status-document-classification-v9`、`event-relationship-v4` 和 `deepseek-v4-flash` 全量运行65份文档，结果保存在 `evaluation/runs/status_opportunity_phase1_v4-statusmatch-signal/`：

- 65/65 文档完成，84 次模型调用，0 次分析失败；文档标签 65/65；
- 文档内活动数量 64/65；事件分组 TP 18、FP 0、FN 1、TN 1412，Precision 100%、Recall 94.74%、F1 97.30%；
- Flying Blue 四份材料正确聚合，Best Western 美国/加拿大入口正确聚合，KM 与 Kenya 正确拆分；
- 两个剩余错误是雅高混合文章随机漏抽等级房晚，以及 Malaysia Airlines 中文事件未被 FFB 英文项目名召回。

马航错误定位为实现缺口：很旅行分类输出的项目名只有“马来西亚航空”，原逻辑只用子域标签 `enrich` 与项目名比较，尚未利用链接锚文本 `[马来西亚航空](...)`。修复后，系统同时使用子域项目名或非通用链接锚文本完成活动归属，并保留多活动文档防串线测试；关系行为版本递增为 `event-relationship-v5`。

第二次使用同一冻结 v4、`status-document-classification-v9`、`event-relationship-v5` 和 `deepseek-v4-flash` 全量运行，结果保存在 `evaluation/runs/status_opportunity_phase1_v4-statusmatch-anchor-signal/`：

- 65/65 文档完成，首次新鲜运行 85 次模型调用，0 次分析失败；
- 文档标签 65/65，`STATUS_OPPORTUNITY` 与 `NONE` 的 Precision、Recall、F1 均为 100%；
- 文档内活动数量 65/65；事件分组 TP 19、FP 0、FN 0、TN 1412，Precision、Recall、F1 均为 100%；
- Flying Blue 四份材料使用同一预测事件；Malaysia Airlines 中英文材料使用同一预测事件且 Garuda 保持独立；Best Western 美国/加拿大入口合并；KM 与 Kenya 保持分离；雅高混合文章正确输出等级房晚与 Kenya 两项；
- 同目录立即重跑没有新增模型调用、事件或错误，验证数据库级重跑幂等。目录中的最终 `report.json` 记录该次重跑，因此 `model_calls=0`，同时以 `cached_outputs=85` 保留首次新鲜运行的结构化输出规模。运行报告明确 `temporal_metrics.included=false`，本轮没有评测实效性。
