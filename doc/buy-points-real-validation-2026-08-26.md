# AwardWallet 买分优惠真实验收（2026-08-26）

## 范围与环境

- 观察时间：`2026-08-26T09:07:48.812276+00:00`（北京时间 17:07）
- 唯一请求 URL：`https://awardwallet.com/news/current-promotions-buy-points-miles/`
- 页面最终 URL 的 host/path 校验通过。
- 真实页面解析和连续两次采集/处理在隔离的内存 SQLite 中执行，不使用 AI，不写入本地开发业务数据。
- 本地开发 PostgreSQL 随后完成 `0012_discovery_cursor -> 0013_buy_points -> 0012_discovery_cursor -> 0013_buy_points` 往返，并重新播种来源。

## 页面观察

- 标题：`18 Current Promotions for Buying Airline Miles and Hotel Points (Up to 150% Bonus Points)`
- 标题声明数量：18
- 主分区数量：航空 11、酒店 6、其他交通 1，总数 18
- 顶部推荐唯一匹配：4
- 无截止日期：6
- 页面 `article:modified_time`：`2026-08-25T20:02:47+00:00`
- 代表性逐字证据：项目 `Avianca (LifeMiles)`，优惠原文 `Buy LifeMiles with up to a 145% bonus`；结构字段和 evidence 中原文一致。

标题声明数、三个主分区总数和最终活动数一致。顶部推荐只补充已有主活动，没有创建第 19 条活动。

## 连续运行幂等结果

第一次运行：

- 发现/考虑：1 / 1
- 新增 `DocumentVersion`：1
- 待处理/成功/失败：1 / 1 / 0
- 最新活动数：18

第二次紧接运行：

- 再次请求同一个固定页面：是
- 新增 `DocumentVersion`：0
- 待处理/成功/失败：0 / 0 / 0
- 最新活动数仍为 18

最终数据库计数：

- `document_versions`：1
- `buy_points_snapshots`：1
- `buy_points_offers`：18
- `job_runs`：1
- `status_events`：0
- `article_opportunities`：0
- `fact_sets`：0
- `briefs`：0

由此确认相同正文不会重复创建文档、快照或活动，也没有进入会籍事件、文章机会、FactSet 或简报链路。买分运行没有构造或调用 AI provider，模型调用增量为 0。

## 失败保护核对

固定夹具测试已覆盖标题数量不一致的后续 `DocumentVersion`：处理记录进入 `FAILED`，失败输入不写快照或活动，当前读取仍返回前一个成功快照；安全错误摘要不包含整页 HTML。真实页面验收期间没有人为向开发数据库写入失败页面。

## PostgreSQL 迁移结论

开发 PostgreSQL 升级后仅新增 `buy_points_snapshots` 和 `buy_points_offers`，唯一约束与查询索引存在。降级后两表消失，再升级成功。往返前后以下既有表计数完全相同：

- `sources` 8（往返验证前；之后播种新增 AwardWallet 买分来源）
- `source_items` 73
- `document_versions` 117
- `status_events` 8
- `article_opportunities` 9
- `fact_sets` 30
- `briefs` 30

迁移往返没有修改或删除既有来源材料和会籍业务数据。最终开发数据库停在 `0013_buy_points`，并已执行 `seed-sources`，`awardwallet_buy_points_page` 处于 `P1D` 自动调度配置。
