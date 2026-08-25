# 通用文章 V2 架构与验收

## 当前边界

- 通用公开来源只有 `loyaltylobby_feed`。
- `status_services_mail` 继续只服务 StatusMatch 官方 HOME + FAQ 项目链路。
- 其他公开来源的注册、适配器、原文和 V1 历史结果保留，但关闭启用和自动调度。
- 当前不做跨文章候选召回、相似度、关系 AI、事件合并或跨来源事实协调，也不创建预留的分组表或空关联框架。

`article_pipeline` 是独立文章领域包，不导入 `journeyplus.statusmatch`。跨域选择只在 `article_operations` 和自动编排层发生。

```text
LoyaltyLobby DocumentVersion
          │
          ├─ 精确项目专属 *.statusmatch.com
          │       └─ StatusMatch 第三方补充（原有一次 AI，同时提取候选映射）
          │
          └─ 普通文章
                  ├─ 批量标题筛选（只传 ID + 标题）
                  │      ├─ DROP：停止，不读正文
                  │      └─ PASS / NEEDS_BODY
                  ├─ 一次正文理解
                  │      └─ 最终标签 + 0..N ArticleOpportunity + FactSet + 逐字证据
                  └─ 每个机会一次简报（只读已持久化 FactSet）
```

## 调用预算与失败边界

不计最多两至三次的有限纠错重试：

| 场景 | AI 调用 |
|---|---:|
| 最多 25 个新标题 | 1 次批量调用 |
| 高置信度 `DROP` | 只有摊销的标题调用 |
| 单机会正文正例 | 正文 1 + 简报 1 |
| 一篇文章含 K 个独立机会 | 正文 1 + 简报 K |
| 标题通过但正文为 `NONE` | 正文 1 |
| 精确 StatusMatch 第三方文章 | 通用 0；专用补充 1 |
| 相同输入与版本完整重跑 | 0 |
| 通用关系或 AI 事实协调 | 0 |

标题批次失败、缺项、重复 ID 或低置信度 `DROP` 都保守转换为 `NEEDS_BODY`。正文结构或证据失败保存为待复核分析。简报失败不回滚文章分析和事实；再次运行只重试缺失简报。标题、正文和简报各自以输入、模型、提示词及 Schema 版本形成独立幂等键，因此只升级一个阶段时不会强制重跑其他 AI 阶段。

## 数据与低耦合

V2 使用独立的 `ArticleAnalysisRecord`、`ArticleOpportunityRecord`、`ArticleBriefRecord`，不把普通文章写入共享 `StatusEvent`。事实字段继续复用 `FactField`、`ApplicationRoute`、`StatusMapping` 和 `Brief` 等稳定核心契约，因此前端可以用相近读取模型展示，但生命周期、持久化和专用处理器互不依赖。

每个机会保留稳定 ID、SourceItem、DocumentVersion、canonical URL、发布时间、项目、目标等级、摘要、活动窗口、行动链接、完整事实、逐字证据、正文签名和事实签名。以后需要跨来源分组时，可以把最新成功 ArticleOpportunity 作为只读输入另建投影；当前表中没有 `group_id`、候选、关系类型或关系置信度字段。

StatusMatch 第三方候选映射使用中立 `membership` 契约和独立 provenance。候选状态分为 `CORROBORATED / CANDIDATE / CONFLICTING / REJECTED / APPROVED`；默认官方图仍只读取 ACTIVE 项目的当前官方 FactSet，未批准的第三方声明不会进入主图。批准和拒绝是显式人工操作，且不会修改官方 FactSet。

## CLI 与回滚

```bash
uv run journeyplus collect loyaltylobby_feed --limit 100
uv run journeyplus process-pending --source-id loyaltylobby_feed --limit 100
uv run journeyplus run-source loyaltylobby_feed --limit 100
uv run journeyplus run-daily
uv run journeyplus automation-status
```

默认使用 V2 并启用标题 DROP：

```bash
JOURNEYPLUS_GENERIC_ARTICLE_PIPELINE=v2
JOURNEYPLUS_GENERIC_TITLE_DROP_ENABLED=true
```

短期回滚可以把 pipeline 设为 `v1`；只关闭标题阻断、仍保留 V2 时把 `JOURNEYPLUS_GENERIC_TITLE_DROP_ENABLED=false`。V1 代码和历史数据未删除。回滚不会删除 V2 结果，读取端仍可按各自表查询历史。

## 2026-08-24 LoyaltyLobby 真实验收

从真实 Feed 采集 10 篇 8 月 24 日文章，并逐篇阅读保存的完整原文后核对标题决策、正文结论、事实、引用和简报：

| 结果 | 数量 | 人工核对结论 |
|---|---:|---|
| `PASS → STATUS_OPPORTUNITY` | 2 | Radisson ClubAvolta 匹配、ALL Accor Gold 快速通道均为真实会籍机会 |
| `NEEDS_BODY → NONE` | 1 | Accor/Flying Blue/Qatar 内容是积分或里程抽奖，不是会籍获取 |
| `DROP` | 7 | 分别为奖励积分、里程贬值、酒店折扣、休息室用餐、行李失窃、酒店签约和积分转换奖励 |

人工逐字段核对结果：

- Radisson：ClubAvolta Gold → Radisson Premium、Platinum → VIP 两条直接等级映射正确；当前申请路径只有账户链接。原文中的邮件是历史方法，未被保存成当前路径，简报也保留“此前使用、当前未确认”的限定。原文没有当前申请窗口，日期保持未知。
- ALL Accor：一次性把巴西合作伙伴积分转换为 15,000 ALL Reward Points 可获得 90 天 Gold，90 天内完成 5 个合格房晚可延长至 2027-12-31。申请窗口正确拆为 2026-08-24 至 2026-08-28，生命周期为 `ACTIVE`；积分转换没有被误当作会籍等级映射，申请地域没有由合作伙伴所在地臆测。
- 两篇正例共保存 37 个事实/路径/映射证据引用，全部通过逐字正文定位；Markdown 列表中的两段引用也通过可读文本投影逐字定位。
- 标题影子报告：10 篇、2 个已知正例、正例 `DROP=0`，决策为 `DROP=7 / NEEDS_BODY=1 / PASS=2`，阶段门通过。
- 全冷启动预算为 1 个标题批次 + 3 个正文 + 2 个简报，共 6 次调用；稳定输入完整重跑实测 `selected=0, model_calls=0`。

同批真实原文还在隔离的内存数据库中运行了旧 V1 作为影子基线。V1 同样得到 2 个正例、2 个机会和 2 个简报，但使用 15 次调用：10 次全文分类、1 次关系判断、2 次 AI 事实整理、2 次简报，用户输入约 374,718 字符。V2 冷启动只需 6 次，用户输入约 47,682 字符；10 篇文章的正文总量为 326,076 字符，V2 只向正文模型发送 3 篇、25,986 字符。调用数减少 60%，提交给正文模型的正文量减少约 92%，同时去掉了全部通用关系和二次事实 AI。V1 影子库在进程结束后即丢弃，未写入业务 PostgreSQL。

8 月 24 日样本没有项目专属 `*.statusmatch.com` 链接，因此另用 8 月 3 日真实文章《Kenya Airways SkyTeam Elite Plus Platinum Match For ALL Accor Gold, Platinum & Diamond》补测。正文包含 `https://kenya-airways.statusmatch.com/`，确定性路由已创建且通用 V2 实测 `selected=0, model_calls=0`。

自动化测试另外覆盖一篇正文含两个独立项目和行动入口的场景：一次正文调用生成两个隔离机会，再分别生成两个简报，总调用为 1 个标题批次 + 1 个正文 + 2 个简报；第二次完整运行为 0 调用。

## 验证命令

```bash
uv run alembic upgrade head
uv run pytest -q
openspec validate simplify-generic-article-pipeline --strict
```

SQLite 已验证 `0009 → 0010 → 0009` 往返；PostgreSQL 也在一次性隔离数据库中验证 `0009 → 0010 → 0009 → 0010`，随后删除测试库，开发库已升级到 `0010_generic_article_v2`。迁移只新增 V2 表和第三方 `mapping_claims` 字段，不删除旧来源、DocumentVersion、V1 事件、FactSet 或 Brief。
