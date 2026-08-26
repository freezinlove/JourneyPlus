# 2026-08-26 统一会籍树真实验收

## 结论

本次在本地真实 PostgreSQL 的完整 LoyaltyLobby 原文和当前产物上验收。8 月 24 日 URL 日期批次共
10 篇：`DROP=7`、`NEEDS_BODY → NONE=1`、`PASS → STATUS_OPPORTUNITY=2`。统一树当前读取 2 条
普通文章直接贡献，均来自 Radisson/ClubAvolta 正例；项目关联的 Kenya 文章只有 4 条 highlights，
普通文章分析、机会和统一树贡献均为 0。

树和生命周期没有新增 AI 调用。Kenya 的旧结果为 `v7/schema1`，为实际验证纯 highlights 的
`v8/schema2` 首次重算使用 2 次模型尝试（第一次未通过本地校验，第二次成功）；相同输入紧接着
重跑为 `selected=0, model_calls=0`。8 月 24 日普通文章集稳定重跑同样为 0 次调用。

## 8 月 24 日文章集

10 篇标题共用 1 次批量标题调用。仅 `PASS` 或 `NEEDS_BODY` 的 3 篇读取正文；两个机会各生成一篇
简报，因此原始冷启动总预算是 `标题 1 + 正文 3 + 简报 2 = 6` 次。此次统一树变更没有重新调用
这些已经幂等完成的 AI 阶段。

| 原文（标题缩写） | DocumentVersion | 决策 | 正文/简报 | 当前结果 | 树映射 | 可见策略 |
|---|---|---|---:|---|---:|---|
| [Accor’s Raffles for Flying Blue/Qatar](https://loyaltylobby.com/2026/08/24/accors-raffles-for-afklm-flying-blue-qatar-airways-privilege-club-members/) | `97debd20-5c2b-4222-abff-95fad1ee2b96` | NEEDS_BODY | 1/0 | NONE，积分/里程抽奖 | 0 | 不适用 |
| [Citi ThankYou → LHW 25% Bonus](https://loyaltylobby.com/2026/08/24/citi-thankyou-to-lhw-leaders-club-25-conversion-bonus-august-23-september-19-2026/) | `b220992c-da10-412d-8a1d-a852b6f44b25` | DROP | 0/0 | 积分转换奖励 | 0 | 不适用 |
| [IHG Kyoto 14 Hotels Conversion](https://loyaltylobby.com/2026/08/24/ihg-signs-a-deal-to-convert-14-kyoto-ms-hotels-under-garner-holiday-inn-express-brands/) | `5c846a63-4a32-4603-b105-155d68a995bd` | DROP | 0/0 | 酒店签约 | 0 | 不适用 |
| [ALL Accor Gold Fast Track](https://loyaltylobby.com/2026/08/24/all-accor-status-fast-track-offer-from-brazilian-partner-programs-conversion-required-august-24-28-2026/) | `16132be5-c2bf-4d39-9c20-d537f0f07ce8` | PASS | 1/1 | 1 个会籍机会 | 0 | EXPLICIT_DEADLINE |
| [Thai VietJet Baggage Claim](https://loyaltylobby.com/2026/08/24/thai-vietjet-passengers-claims-loss-of-600000-baht-baggage-items-due-to-pilferage/) | `96937a0b-a354-499f-a5d0-c8489b5f0a29` | DROP | 0/0 | 行李失窃 | 0 | 不适用 |
| [AA Flagship Dining Access](https://loyaltylobby.com/2026/08/24/american-airlines-flagship-dining-access-expands-to-business-class-passengers-starting-september-15-2026-lax-reopening-late-2026/) | `fb34f8a1-3639-4f1e-ad58-137d8b3fc97f` | DROP | 0/0 | 休息室餐饮 | 0 | 不适用 |
| [IHG 30% Destination Deals](https://loyaltylobby.com/2026/08/24/ihg-30-off-destination-deals-for-stays-in-most-markets-august-28-october-11-2026-book-by-august-30/) | `c81a5c6c-4494-43a2-a4e8-0e92d9a25bb4` | DROP | 0/0 | 酒店折扣 | 0 | 不适用 |
| [Flying Blue Mileage Devaluation](https://loyaltylobby.com/2026/08/24/air-france-klm-flying-blues-email-about-20-to-25-mileage-devaluation-on-september-8-2026/) | `f0be945a-8c5a-4e38-bbe6-92dc2dec9063` | DROP | 0/0 | 里程贬值 | 0 | 不适用 |
| [Radisson ClubAvolta Status Match](https://loyaltylobby.com/2026/08/24/radisson-rewards-clubavolta-status-match-is-back-for-2026/) | `6055d572-4772-4900-8906-a4df7ea5efdb` | PASS | 1/1 | 1 个会籍机会 | 2 | DEFAULT_180_DAYS |
| [IHG Up To 6,000 Bonus Points](https://loyaltylobby.com/2026/08/24/ihg-one-rewards-up-to-6000-bonus-points-for-stays-september-1-30-2026/) | `deac3eba-7828-4f1b-be4e-7a496ffa1f77` | DROP | 0/0 | 奖励积分 | 0 | 不适用 |

逐篇阅读保存的完整正文后，7 篇 DROP 的主题与标题判断一致；Raffles 正文实际是赢取 Accor、
Flying Blue 或 Qatar 奖励积分/里程的抽奖，不是直接获得、升级、匹配或延长会籍，NONE 正确。

## 案例一：无截止日期、180 天和树分支撤销

- 原文：[Radisson Rewards ClubAvolta Status Match Is Back For 2026](https://loyaltylobby.com/2026/08/24/radisson-rewards-clubavolta-status-match-is-back-for-2026/)
- SourceItem：`e8b844c8-0d69-4368-b93c-fc0980e2123e`
- DocumentVersion：`6055d572-4772-4900-8906-a4df7ea5efdb`
- 当前成功 ArticleAnalysis：`f71ec080-191e-523d-b0bc-c2e6caaa6fea`
- 当前 ArticleOpportunity：`3a2075be-f92b-5667-9ea5-a8ff86540aa1`

人工逐条核对：

| 输出 | 原文逐字定位 | 判断 |
|---|---|---|
| ClubAvolta Gold → Radisson Rewards Premium | `ClubAvolta Gold to Radisson Rewards Premium` | 正确、方向正确 |
| ClubAvolta Platinum → Radisson Rewards VIP | `ClubAvolta Platinum to Radisson Rewards VIP` | 正确、方向正确 |
| 当前路径为账户链接后自动匹配 | `the match would be automatic after you link accounts` | 正确，简报使用“可能自动匹配”保留原文语气 |
| 邮件是旧路径 | `Previously, however, you needed to email ...` | 正确，没有误写成当前申请路径 |
| 截止日期为空 | 全文没有当前活动截止日 | 正确，没有把 180 天写成活动 deadline |

Feed 发布时间是 `2026-08-25T02:30:53Z`，所以 `timedelta(days=180)` 的内部可见截止为
`2027-02-21T02:30:53Z`，策略为 `DEFAULT_180_DAYS`。在回滚事务中的实测：

- 截止前 1 秒查询 `ClubAvolta Gold`，存在 `Radisson Rewards Premium` 分支；
- 精确到截止边界查询，该分支消失；
- 生命周期扫描把目标机会软归档为 `STALE_180D`；
- 软归档后即使把查询时间拨回截止前，该贡献仍不可见；
- 事务回滚后数据库的 `archived_at`、`archive_reason` 均恢复为空。

同样的 Platinum → VIP 分支共用该机会和截止。树读取只使用最新成功分析，库中历史重试产物不会重复
贡献。

## 案例二：明确截止优先

- 原文：[ALL Accor Status Fast Track Offer From Brazilian Partner Programs](https://loyaltylobby.com/2026/08/24/all-accor-status-fast-track-offer-from-brazilian-partner-programs-conversion-required-august-24-28-2026/)
- SourceItem：`46e97a7d-53f0-40f2-aadd-86f13ad1f332`
- DocumentVersion：`16132be5-c2bf-4d39-9c20-d537f0f07ce8`
- 当前成功 ArticleAnalysis：`9b460dd6-e590-590e-8850-7942d4e74897`
- 当前 ArticleOpportunity：`f74bb5c0-16ef-5995-b077-f885c8490259`

原文明确写了 `between August 24 and August 28, 2026`、转换达到 15,000 ALL points 后获得 90 天
Gold，以及 90 天内完成 5 个 eligible nights 可延长至 2027-12-31。当前事实和简报均忠实保留这些
条件。机会截止被规范化为 `2026-08-28T15:59:59.999999Z`，可见策略为
`EXPLICIT_DEADLINE`，没有使用默认 180 天。

该活动是积分转换触发的 Gold 快速通道，原文没有“原会籍等级 → 目标会籍等级”的直接映射，因此
`status_mappings=[]`，不会为了让它进入树而臆造边。回滚事务在截止边界运行生命周期后，目标机会的
归档原因为 `DEADLINE_EXPIRED`；回滚后原记录未被改变。

## 案例三：StatusMatch 关联文章只进入 highlights

- 原文：[Kenya Airways SkyTeam Elite Plus Platinum Match For ALL Accor](https://loyaltylobby.com/2026/08/03/kenya-airways-skyteam-elite-plus-platinum-match-for-all-accor-gold-platinum-diamond/)
- DocumentVersion：`52072d7e-6d2f-4a0b-9de6-8e41285663aa`
- Route：`ff8d6dff-2684-4860-8e38-d4cba7847702`
- 当前 Supplement：`2e8c43fd-c9b5-49ab-8e58-1567ff2b9008`
- 官方 FactSet：`d8cfba8a-f7ce-4301-83e6-5511bed8278f`
- 官方 Brief：`e97bd7b0-d8e9-4156-927e-baca8fec713a`

新链路生成 4 条 highlights，人工逐字核对如下：

1. SkyTeam Elite 的额外行李、优先值机和优先托运行李，引用完整存在；
2. SkyTeam Elite Plus 的全部 SkyPriority 和“大多数航线”休息室权益，范围限定保留；
3. 更新 Asante 号码后在 KQ/SkyTeam 系统即时可验证，未额外推导“无需等待实体卡”；
4. 作者不确定 Asante 积分累积及合作伙伴兑换表/预订流程是否成熟，保持为作者观察而非官方事实。

当前 Supplement 的历史兼容 `mapping_claims=[]`。该 DocumentVersion 的普通 ArticleAnalysis 数为 0、
ArticleOpportunity 数为 0、统一树贡献数为 0，所以没有 180 天策略或映射字段。重算前后官方 FactSet
和 Brief ID 完全相同，StatusEvent 当前指针未改变。

## 统一图和自动化边界

真实数据库当前统一审计为 1,178 个有效贡献、1,168 条去重直接边、2 条规则；其中普通文章贡献恰好
为上面的 Radisson 两条，官方 UNAVAILABLE 排除数为 208。用户树不会返回 contributor、provenance
或来源等级字段。

当前真实普通文章样本没有可形成混合多跳或“官方与文章同边”的另一篇文章，不能诚实地把合成夹具
冒充真实原文。对应边界已由数据库集成测试覆盖：

- 官方 A→B + 文章 B→C；
- 文章 A→B + 官方 B→C；
- 官方与文章同一 A→B 只显示一边但审计保留两份证据；
- 两篇文章不同期限，先到期的 contributor 撤下后边仍在，最后一项到期才消失；
- 同边不同条件变体、UNAVAILABLE、冲突、无证据、关联文章、循环、交叉引用和遍历上限。

统一服务两次连续构建的用户树和管理员审计逐字段一致，过程没有 AI provider，也不持久化 A→C
传递边。

## 验证记录和限制

- `uv run python -m compileall -q src`：通过；
- `uv run pytest -q`：276 项全量通过；
- SQLite `0011` upgrade/downgrade 和回填：自动化测试通过；
- 本地 PostgreSQL 已升级到 `0011_mapping_visibility`；
- 真实边界归档使用事务回滚，未把测试时间写入业务数据；
- 公开网页在本次独立抓取时返回 HTTP 402，因此人工核对使用采集时保存的完整
  `DocumentVersion.normalized_body`；文章 URL、原文和逐字证据仍完整保存在库中；
- 真实库暂时没有第二条能与 Radisson 形成混合多跳/同边去重的普通文章，这部分保留为自动化集成
  测试覆盖风险，后续出现真实样本时应追加人工验收。
