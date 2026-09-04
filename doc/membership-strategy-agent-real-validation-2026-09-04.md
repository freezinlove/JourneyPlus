# 会籍策略 Agent 真实链路验收（2026-09-04）

## 结论

会籍策略 Agent 已在项目真实 PostgreSQL、真实统一会籍图、真实 `deepseek-v4-flash` Provider 和当前 StatusMatcher 公司页上跑通。主流程能够从中文自然语言完成目标与取舍理解、复用已确认会籍、查询正式路线、按需调查实际申请经验并给出首选和备选；无方案流程能够提出一次最小调整，在用户拒绝后主动提供持续跟进选项，并仅在确认后保存等待目标。

本次验收以“链路和架构大体正确”为目标，不把社区样本描述成真实审批概率，也不补建会籍权益数据库。StatusMatcher 调查是用户在本次实施任务中明确要求的受控验证；正式运行配置仍保持默认关闭，生产启用前仍需取得书面许可、授权接口或其他明确授权。

## 环境与基线

- 本地 Docker PostgreSQL 可用，数据库由 `0017_statusmatch_terms` 成功升级至 `0018_membership_agent (head)`。
- 升级前后核心事实数量保持为：`status_events=8`、`article_opportunities=23`、`fact_sets=63`。
- 真实规范化目录包含 376 个会籍节点。
- 验收前后持有会籍均为 `lufthansa miles more::senator` 和 `marriott bonvoy::platinum elite`，没有新增或覆盖用户会籍。
- 实际 AI 配置为北京地域 `deepseek-v4-flash`；密钥只通过环境配置读取，验收输出未显示密钥。

## 自然语言推荐链路

提交文本：

> 我已经有汉莎 Miles & More Senator（金卡），想要天合联盟的高等级会籍。优先路线短，可以接受合理付费和挑战；请结合 StatusMatcher 上的真实申请经验再推荐。

Agent 将其结构化为：

- 已有会籍：目录中的 `lufthansa miles more / SENATOR`，因数据库已有相同会籍，没有再次请求写入确认；
- 目标：天合联盟，偏好高等级；
- 硬条件：费用不限、允许挑战；
- 主观偏好：路线短；
- 实际经验：明确要求调查。

确定性候选服务从两个当前持有会籍出发，返回 12 条满足目标和硬条件的路线，其中 6 条为一步路线。最终真实回合返回 `HTTP 200 / RECOMMEND / COMPLETED`：

- 首选：`lufthansa miles more::senator → lotusmiles vietnam airlines::gold`；
- 备选一：`lufthansa miles more::senator → flying blue::gold`；
- 备选二：`lufthansa miles more::senator → kenya airways asante rewards::gold elite plus`。

这三条路径与统一匹配图中的正式边一致，分别引用现有 Lotusmiles、Flying Blue 和 Kenya Airways 机会事实与官方申请/证据页面。Agent 没有创造图外路线。返回中强制附带“联盟精英等级等价尚未结构化”的限制，明确高等级选择只是基于候选等级名称的比较，不是官方联盟等级等价结论。

## StatusMatcher 人工核对

Controller 只允许 Agent 从正式候选中选择三条调查。客户端按生产默认上限读取每个候选最多两个 `statusmatcher.com/company/*` 页面，不接受模型提供的任意 URL，不把结果写入事实库或统一图。

本次页面观察为：

| 正式路线 | 当前可比自报 | 结构化结果 | 人工核对 |
| --- | ---: | --- | --- |
| Lufthansa → Flying Blue | 2 | `DENY=2`，信号较弱 | [Air France / Flying Blue 页面](https://statusmatcher.com/company/air-france)及第二页当前可见两条 Lufthansa 来源拒绝案例；一条提到付费后被拒，另一条提到活动过期或地区不可用 |
| Lufthansa → Vietnam Airlines Lotusmiles | 2 | `MATCH=2`，信号一般 | [Vietnam Airlines 页面](https://statusmatcher.com/company/vietnam-airlines)及第二页当前可见两条 Lufthansa 来源成功案例，分别提到付费后获得会籍和约 24 小时处理 |
| Lufthansa → Kenya Airways Asante Rewards | 0 | 证据不足 | [Kenya Airways 页面](https://statusmatcher.com/company/kenya-airways)及第二页在本次受限窗口内没有 Lufthansa 来源可比报告，因此没有借用其他来源项目案例 |

另外用 Marriott → Kenya Airways 的正式候选核对了可比性过滤：同一 Kenya Airways 页面两页内可见 2 条 Marriott 来源 `MATCH`，客户端只在该 Marriott 来源路线下计入，不会错误加到 Lufthansa 来源路线。

页面自身展示的汇总比例没有被当作本系统的真实成功率。Agent 只使用当前受限窗口内、方向和来源项目可比的报告计数，并始终返回“用户自报、不代表真实审批概率或通过保证”的限制。

真实联调先后发现并修正了三个问题：

1. 用户明确要求经验调查时，Controller 现在必须先执行受限调查，不能让模型静默跳过；Agent 仍负责在最多三条正式候选中选择调查对象。
2. Provider 偶尔把空列表输出为 `null`，现在只把这种无语义差异的值规范化为空列表，路线 ID、动作、数量和写入门仍严格校验。
3. 公司页不足固定条数并不代表没有下一页；客户端现在始终遵守配置的固定页数上限，并对跨页重复报告去重。

人工复核还发现模型曾加入数据库不支持的退款风险。最终实现会过滤休息室、行李、早餐、升房、退款、申诉和客服等越界风险，并在 Prompt 中明确这些内容不属于当前数据库或 Agent 范围。

## 无方案、调整与持续跟进链路

提交文本：

> 我用现有的汉莎 Miles & More Senator，只想免费匹配到 Flying Blue Gold；不限制是否有挑战。如果没有免费路线，先别直接推荐付费路线。

真实执行结果：

1. 确定性查询把现有 Flying Blue 官方路线放入 `nearby_routes`，唯一偏离条件是 `cost_policy`；
2. Agent 提出一个 `cost_policy → ALLOW_FEE` 调整，并展示该路线存在 EUR/USD 申请费；
3. 用户模拟选择“拒绝”，Controller 没有应用调整；
4. 同一个 Agent 主动返回 `OFFER_WAITING / AWAITING_WAIT_CONFIRMATION`；
5. 用户模拟确认后，只创建一个 `ACTIVE` 等待目标，保存的条件仍是 `FREE_ONLY`；
6. 状态 API 能读回该目标；验收结束后通过 `CANCEL_WAIT` 清理，数据库当前 `ACTIVE` 等待目标数量为 0。

单元与集成测试另外验证：无命中和相同候选签名时模型调用为 0；首次新签名命中时恢复同一 Agent 一次；结果只展示一次并清除等待表中的临时正文；恢复失败不推进签名，可由后续日程重试。

## 实际服务启动

使用以下真实启动入口在 `127.0.0.1:8099` 临时启动并正常关停：

```bash
uv run journeyplus product-api --host 127.0.0.1 --port 8099
```

启动过程成功检查 PostgreSQL 和 Alembic head。`GET /agent`、`GET /v1/agent/state`、`GET /v1/status-holdings` 均返回 200；状态接口报告 `available=true`，现有两个持有会籍保持不变。

## 自动化验证

```bash
uv run openspec validate implement-membership-strategy-agent --strict
uv run python -m compileall -q src
node --check src/journeyplus/product/static/app.js
uv run pytest -q
```

OpenSpec 严格校验、Python 编译、前端 JavaScript 语法检查和完整 pytest 套件均通过。SQLite 覆盖合约和状态机，真实 PostgreSQL 覆盖迁移、目录、匹配图、模型回合和服务启动。

## 已知数据边界

- 当前没有结构化、可比较的联盟等级等价和会籍权益目录，Agent 不优化休息室、行李、早餐、升房等权益。
- 当前费用事实可能同时包含多个地区、来源类别和目标等级，Agent 必须把它们展示为需核对的候选费用，不能声称某个金额必然适用于当前用户。
- StatusMatcher 是社区自报且页面会变化，本次计数只代表 2026-09-04 验收时受限页面窗口；正式自动读取仍需另行授权。
- 产品仍是本地单用户形态，只允许一个当前等待目标；短期交互默认 24 小时过期，并由状态读取或每日流程删除。
