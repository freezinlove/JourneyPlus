# 个性化会籍匹配产品运维说明

> 本文只描述当前可运行产品。当前产品总边界见 [个性化会籍匹配产品总方针](./personalized-status-match-product-direction.md)，单 Agent 的行为边界见 [会籍策略 Agent 产品方针](./personalized-status-match-agent-direction.md)，实现约束见 [技术基线](./personalized-status-match-agent-technical-baseline.md)。早期文档中关于“无个性化页面”“Agent 尚未实现”“买分参与默认自动调度”或继续扩展多 Agent 的表述已经过期；历史验收数据仍保留参考价值。

## 产品边界

当前产品解决两层相连的问题：确定性底座保存会籍并计算匹配事实；会籍策略 Agent 理解用户的自然语言目标和取舍，在底座候选范围内给出个性化下一步。

- `OpportunityKind` 只有 `STATUS_MATCH` 和 `OTHER`。
- `STATUS_MATCH` 进入个性化匹配图；`OTHER` 不进入图，但照常生成、保存和展示简报。
- 默认地区是中国。地区信息只显示 `明确包含`、`明确排除` 或 `未明确` 提示，不参与过滤或拦截。
- 一个项目只保存一个当前持有等级；再次添加同一项目会替换旧等级。
- 后端可达关系没有业务深度上限，并保留闭环边、多条入边和重复汇合；只有默认 5000 个节点的技术响应预算会截断异常大图。匹配页在该完整响应上做确定性最短路径投影：每个会籍只画一次，只保留最近到达边，不绘制闭环和额外汇入边。
- 除 `/agent` 和 `/v1/agent/*` 外，现有产品页面和确定性 API 不调用 AI。Agent 只读取确定性事实候选，不接管事实、可达性或活动生命周期判断。

## Agent 运行边界

JourneyPlus 当前运行形态是“确定性会籍匹配底座 + 单会籍策略 Agent”，不是多 Agent 系统。Agent 负责自然语言目标理解、必要确认、基于程序候选的取舍式推荐、受限的 StatusMatcher 经验调查、一次最小条件调整和一个用户确认的等待目标；事实、路径、价格、期限与活动状态仍由当前底座提供。

运行能力包括：

- 一个能够根据上下文和程序观察自主选择“确认、查询、调查经验、提出调整、提出持续跟进或结束”的 Agent 交互入口；
- 将自然语言中的已有会籍形成候选理解，经用户确认和目录校验后再调用现有持有会籍服务；
- 按用户目标与硬性取舍返回正式候选，并在无解时确定性返回只偏离一个条件的近似候选；
- 在取得明确授权后，对最多一个首选和两个备选执行 StatusMatcher 按需经验调查；该能力不恢复 `statusmatcher_reports` 批量来源，不发现新活动，不写入官方事实或统一图，也不长期保存报告正文；
- 只保存一个经用户明确确认的等待目标；新目标会原子替换旧目标，并支持通过自然语言重新建立、取消和结束；
- 在现有每日流程更新机会后确定性检查等待目标：没有新候选时不调用 Agent，首次命中时只恢复一次 Agent 并产生一次去重通知；
- 每个 HTTP 回合最多三次模型调用、一次关键追问、一次条件调整、最多三条经验候选和最多两个备选；超界动作由 Controller 拒绝。

StatusMatcher 自动调查默认关闭，正式启用前必须取得书面许可、授权接口或其他明确授权。启用后仍需用户在自然语言中要求实际申请经验，且数据库已有正式候选；调查只读取允许的公司页、最多两页和三条候选，失败会返回结构化降级观察，不会改写官方事实或匹配图，也不会回退到任意网络搜索。

## 启动

```bash
uv run journeyplus product-api
```

该命令会先连接数据库并升级到 Alembic head。如果当前配置指向项目默认的本地 PostgreSQL 且数据库未运行，命令会自动执行 `docker compose up -d --wait postgres`；若 Docker Desktop 本身没有启动，则在启动 Web 服务前直接给出可操作错误，不会等到用户打开页面后才返回 500。首次空库仍可先手工执行 `uv run journeyplus seed-sources` 导入来源配置。

默认监听 `127.0.0.1:8000`。可用 `--host` 和 `--port` 覆盖；对外监听前需另行补账号、鉴权和部署安全能力。

页面入口：

- `/agent`：输入自然语言会籍、目标和取舍，确认 Agent 的结构化理解，查看首选、备选、风险、经验信号、一次最小调整和当前持续跟进目标。
- `/holdings`：搜索规范化会籍目录，添加、替换或删除持有会籍，并可填写有效期。
- `/matches`：从全部持有会籍同时出发，以唯一卡片展示最近到达路径，并在同一列表展示当前匹配/挑战机会。
- 最近路径连线只在目标等级存在明确结构化费用或原文明确免费时显示费用小标签；多路线价格并列显示，未知费用保持空白。
- `/briefs`：以无卡片的单列条目展示全部当前 Brief；每条仅显示短标题、摘要、个性化会籍路径和更新时间，点击整条进入详情。
- `/opportunities/{id}`：以无卡片的纵向信息流展示简报标题与摘要、个性化会籍路径、注意事项、单一官方入口、会籍映射表、匹配费用表和原文链接。

## 产品 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/v1/agent/turn` | 提交自然语言或确认、拒绝、取消/结束跟进命令 |
| `GET` | `/v1/agent/state` | 读取最近短期交互、当前等待目标和一次性首次命中结果 |
| `GET` | `/v1/membership-catalog?q=` | 搜索规范化会籍节点 |
| `GET` | `/v1/status-holdings` | 读取当前持有会籍 |
| `POST` | `/v1/status-holdings` | 添加会籍；同项目自动替换 |
| `PATCH` | `/v1/status-holdings/{id}` | 更新项目、等级或有效期 |
| `DELETE` | `/v1/status-holdings/{id}` | 删除持有会籍 |
| `GET` | `/v1/personalized-matches` | 读取多根完整可达图和统一机会列表 |
| `GET` | `/v1/briefs?q=&reachable_only=` | 读取全部当前简报 |
| `GET` | `/v1/match-opportunities/{id}` | 读取机会详情、价格、提醒和证据 |

交互式 OpenAPI 文档位于 `/docs`。

## 数据迁移与兼容

`0016_personalized_match` 会执行以下操作：

1. 创建单用户 `status_holdings` 表，并对 `program_key` 建唯一约束。
2. 将受管 StatusMatch 项目确定为 `STATUS_MATCH`；对普通历史事实执行保守的二值类型回填。
3. 从有证据的旧 `cost` 文本中回填简单的“等级 + 金额 + 币种/不可用”价格，原始费用文本保持不变。
4. 将 AwardWallet 买分来源的 `automatic_scheduling` 关闭，但不删除来源、历史快照或手工命令。

`0018_membership_agent` 新增 `agent_interactions` 和 `agent_wait_goals`。前者只保存可恢复的结构化短期状态和最后响应，过期记录由状态读取和每日流程清理；后者保存唯一 ACTIVE 等待目标、候选签名和一次性首次命中结果。两者都不保存模型思维过程、完整聊天历史或 StatusMatcher 页面正文。回滚到 `0017_statusmatch_terms` 会删除这两张 Agent 表，但不影响持有会籍、事实、匹配图和简报。

回滚前应先备份数据库。执行 `uv run alembic downgrade 0015_simple_buy_points` 会删除全部持有会籍，移除回填的类型与路线价格，并恢复迁移前的买分调度标志；事实、简报和买分历史表不会被删除。

## 验证

```bash
uv run python -m compileall -q src
uv run pytest -q
uv run alembic current
uv run openspec validate implement-membership-strategy-agent --strict
```

真实 PostgreSQL 验收还应确认：

- 迁移前后的 `fact_sets`、`article_opportunities`、`briefs` 和 `article_briefs` 数量不变。
- `status_services_mail` 与 `loyaltylobby_feed` 自动运行，`awardwallet_buy_points_page` 仅手工运行。
- Flying Blue、Kenya Airways 和 GHA 的多路线/多等级价格能分别保留金额、币种、不可用状态和原文。
- 临时添加一个真实目录会籍后，可达图能返回路径，且结束验证时回滚临时 holding。
- `/briefs` 同时包含 `STATUS_MATCH` 与 `OTHER`，不能按类型漏掉后者。
- `/agent` 在模型未配置时明确报告不可用且其他 API 正常；配置模型后可从自然语言完成确认、候选查询与推荐。
- 无方案分支最多提出一次调整；拒绝或调整后仍无解时由 Agent 主动提出持续跟进，只有用户确认才保存目标。
- `run-daily` 无等待命中时的 `agent_wait_model_called` 为 false；首次新签名命中时为 true，之后相同签名不重复生成结果。

## Agent 配置与排障

```bash
JOURNEYPLUS_AGENT_INTERACTION_TTL_HOURS=24
JOURNEYPLUS_AGENT_MAX_MODEL_CALLS=3
JOURNEYPLUS_STATUSMATCHER_ENABLED=false
JOURNEYPLUS_STATUSMATCHER_TIMEOUT_SECONDS=12
JOURNEYPLUS_STATUSMATCHER_MAX_RESPONSE_BYTES=1000000
JOURNEYPLUS_STATUSMATCHER_MAX_PAGES=2
```

`JOURNEYPLUS_AGENT_MAX_MODEL_CALLS` 的硬上限是 3；StatusMatcher 超时硬上限 30 秒、响应上限 1 MB、页面上限 2。模型配置缺失时 `/v1/agent/state` 返回 `available=false`，回合接口返回 503；模型首次理解失败返回 502。已经确认并写入会籍后若模型在取舍阶段失败，接口保留会籍写入和事实候选，返回“不替用户猜选”的降级结果。

等待检查复用现有 `run-daily`，不需要额外定时任务。检查错误记录在 `AutomationRun.processing_result.agent_waiting` 和 `DailyCycleSummary` 的 Agent 等待字段，不使已经完成的采集与生命周期处理失效；未成功生成首次命中结果时不会推进候选签名，下次日程可重试。
