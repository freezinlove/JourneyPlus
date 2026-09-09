# ModelPort 人工接入双视角验收（2026-09-09）

本轮基线为 `c642b27`，遵守 [实施总纲](charter.md)。这是重新实际运行的系统侧验收，不沿用上轮通过结论，也不代表第三方模型验收完成。优化方案见 [上下文编排优化方案](context-optimization-plan-20260909.md)。

## 结论

核心数据链路已能工作，模型与 harness 没有业务流程强绑定，12 个工具都能通过真实运行器调用。原话、当前查询、历史引用、版本化资料、事务回执及点击焦点可以传到模型侧，并能追溯到持久化记录。

**本轮不判定“全部达标”：发现两个实际缺口，另有明显上下文效率空间。**

1. 混合已存会籍查询的未解析数量不一致：明列 1 条 `unresolved_sources`，`unresolved_holding_count` 却是 0。
2. 比较表忽略主选/备选角色：模型输入与服务端回执均保留角色，实际浏览器比较表只显示对象顺序及比较值，没有显示角色。

已有测试通过不覆盖这两处缺口。这次按用户要求交付验收结果和优化方案，未修改生产代码/提示词/上下文策略，未提交 Git，未调用第三方模型。

## 方法与证据边界

- 使用真实 `scripts/review_agent_harness.py`：本人读取每次实际 wire messages、工具定义和返回结果，再决定下一次调用或回答。没有事先写好整段工具序列代替判断。
- 第一视角：只依据当前输入、已读结果和实际找回的引用作出决定；测试数据的数据库内容没有提前灌给模型。
- 第三视角：结束对话后用独立 SQL 对照版本、映射、费用、条件、事务/产物记录；结合真实浏览器和架构/故障测试复核。
- 数据库：`journeyplus_eval_deepreview_20260909` 从冻结模板复制并迁移至 0027；故障回归另用 `journeyplus_eval_deepchecks_20260909`。未读写生产数据库业务记录。
- 第一视角沿用生产默认 45 秒单模型请求、180 秒硬回合期限及输入预算，未放大预算。取消例外由操作者明确中断。
- `focus` 用私有诊断驱动恢复原工作区，唯一区别是允许传入工作区 ID；运行器及业务代码保持基线。焦点来自实际浏览器点击。
- 所有模型位置由人工承担；公开 HTTPS 查询只访问资料站，不创建 LLM client、不调用 Workflow。协议与故障测试使用本地传输 fixture。
- 原始证据根目录：`.secrets/agent-harness/20260909/deep-review/`。各会话保留 manifest、request/response JSON、原始响应及历史；不含 API 凭据。临时引用有工作区有效期，原始 JSON 证据保留。

### 本轮规模

| 项目 | 结果 |
| --- | --- |
| 独立工作区 | 6 个；焦点续问复用 routes 工作区 |
| 运行回合 | 24：23 个 COMPLETED，1 个预期 CANCELED |
| ModelPort 输入 | 60 次，其中取消回合没有模型响应 |
| 实际工具调用记录 | 44 次：43 次注册工具调用，1 次故意调用未知工具 |
| 能力覆盖 | 12/12 注册工具 |
| 持久化产物 | 73 个，哈希及工作区关联核对通过 |
| 本地/真实 PostgreSQL 回归 | 138 + 21 = 159 项通过，0 跳过、0 失败 |
| 第三方 LLM 请求 | 0 |

`summary.json` 对工作区去重统计；`focus` 与 `routes` 不能重复累计回合。回归测试是第三视角补充，不冒充本人逐轮对话。

## 第一视角逐场景结果

请求编号均相对于证据根目录。

| 场景 | 实际检查与结果 | 证据 |
| --- | --- | --- |
| SAS Gold 假设来源，无目标，仅读一条 | 无需目录前置即可查询；首条阿斯塔纳，11 个候选中只读 1 个；未保存假设 | routes/001–002 |
| 读完剩余候选 | 受结果容量限制继续返回 7、3 条，游标分别到 8、末尾；共 11 条无重漏；知识缺口与分页完成分开 | routes/003–005 |
| 只比较指定终点路径 | 选择直接阿斯塔纳与直接皇家约旦，未把经过皇家约旦的其他路线当作皇家约旦终点；已知费 49/149 USD，个人资格仍 UNKNOWN | routes/006 |
| 显式比较卡顺序、列、角色 | 回执顺序皇家约旦→阿斯塔纳，列 cost/eligibility 正确；第三视角发现实际表格丢角色 | routes/007–008；browser-workspace.txt |
| 国泰替换来源，目标与双条件 | Cathay 返回真实候选名称，修复为 Cathay Pacific Cathay；100 USD、不接受挑战、皇家约旦无指定等级准确保留；零候选未虚构理由 | routes/009–011 |
| 来源再换汉莎 | query_ref+patch 只换来源，保留其他条件；未偷用默认已存会籍 | routes/012–013 |
| 恢复最初 SAS 条件及展开详情 | 使用原无筛选快照 inspect；核实 49 USD、证件/每人一次、有效至 2026-12-31；199 USD 条件性升档未算入必付申请费 | routes/014–015 |
| 从查路线转为一句话概念 | 直接回答、零工具；仍携带 50,293 bytes 输入，效率不理想 | routes/016 |
| 超出最近 12 条可见消息后找原话 | workspace.read 找回首条原话与真实消息 ID；holdings.read 包含过期记录仍无 SAS | routes/017–018 |
| 目录缺失但明确授权保存 | 原名保存 Nebula Gold、有效期 2027-12-31、NEEDS_CONFIRMATION；读回一致，未新增正式目录 | memory/001–003 |
| 已存来源混合可解析/未解析 | 汉莎与万豪各有候选；星河明确列为未解析，但汇总数量错误，见问题 A | memory/004–005 |
| 清空有效期、笔记冲突恢复 | valid_until:null 正确清空且其他字段保留；故意旧笔记 revision=0 被拒绝，修复为 1 后成功 | memory/006–009 |
| 再次保存同一会籍 | NOOP、同一 holding ref、revision=2，无重复数据 | memory/010–011 |
| 朋友信息、明确不保存、无会籍假设 | sources=none，没有调用写工具，没有拿朋友/已存会籍替代假设 | memory/012–013 |
| 删除与旧修订号 | revision=1 删除冲突，返回 current revision=2；按当前版本删除并清空笔记成功 | memory/014–016 |
| 创建免费等待任务 | 直接调用 waiting.manage，不需要先跑 routes；真实确定性 check 返回 NO_HIT | waiting/001–002；waiting-free-check.json |
| 更新等待条件 | 改允许付费、其他不变；真实 check 返回 RESULT_PENDING，无模型参与 | waiting/003–004；waiting-paid-check.json |
| 等待结果→路线工具→图 | list 返回当前工作区 route refs，compare 展开，再按万豪→汉莎展示；不重新改写目标 | waiting/005–008 |
| 取消等待任务 | CANCELLED、revision=3，历史结果快照/成功展示仍存在 | waiting/009–010 |
| 真实公开经验 | 搜索实际 Alaska 链接，读取 124289，解析原方向 United Platinum→Alaska Platinum；报告提交日期与申请日期区分，可比性 PARTIAL、规范化结果 UNKNOWN | research/001–004 |
| 网页分页、文本/链接范围 | 同 page_ref/hash/observed_at 续读 0–1000→1000–2000 字符，链接 0–26→26–40；未把正文未读部分当已完成 | research/005–007 |
| 错误工具、参数、跨工作区 | UNKNOWN_TOOL、具体 selector INVALID_ARGUMENT、跨工作区 NOT_FOUND；修正 selector 后概览成功 | errors/001–003 |
| 伪造授权、目录歧义及游标错配 | 伪造消息 ID 被 NOT_AUTHORIZED；Gold 有 101 个候选，仅读 2 个；Gold 游标配 Silver 被 STALE_REFERENCE | errors/004–006 |
| 浏览器点击后恢复进程续问 | 点击皇家约旦行产生真实 focus；新 ModelPort 输入携带原 presentation/object；据该条规则回答加拿大居留证不满足护照要求 | focus/001–002；browser-detail.png |
| 模型思考期间取消 | 观察到真实 10 秒 heartbeat 更新后取消，终态 CANCELED，0 工具、无后续写入 | cancel/；external-cancel.json |

所有错误恢复调用是明确的验收故障注入，不应把故意旧 revision/未知工具计为产品自然错误率。`Cathay` 名称修复是正常任务中实际发生的额外调用。

## 第三视角核验

### 数据库事实与数据流

`final-database-audit.json`：44 张正式知识及来源相关表与冻结模板逐表行哈希一致；原有会籍完全一致；人工测试会籍创建→清空→NOOP→删除及等待任务状态可从 journal/receipt 追溯。未发现正式活动、简报或匹配图被 Agent 改写。

`facts-audit.json`：独立 SQL（不调用 RouteService 再证明自身）核对 6 个路线快照中的 15 个路线实例、31 个步骤实例、27 个费用项、104 个条件项：版本均已发布，option/mapping/version 外键对应，明确来源等级在映射范围内，路径节点连续，目标与步骤吻合，费用金额/币种/角色及已知合计一致，有效期/窗口及条件原文一致。实例含重复快照，不能解释为 15 种独立政策。未对现实官方政策是否最新作保证。

浏览器重新载入真实会话，比较对象顺序、费用、待核实标记及单一详情可见。点击对象更新 focus 后，本人从 ModelPort 收到该焦点并据对应版本回答。问题 B 证明仅检查服务端回执不够。

### 架构与执行边界

- 实际链路：ModelPort → 通用 runtime/registry → 独立 handler → 业务服务/显式数据边界 → ToolResult/Artifact → 下一次 ModelPort 输入。
- runtime 不依赖品牌/路线意图分类，没有固定业务工具顺序；零工具、并行读、跨轮原查询、写入及恢复都实际可用。
- Agent/Workflow 是独立控制链；共享已发布知识读取、用户数据服务边界、版本化展示引用。它们不是完全无共享资源的两个部署，也不应描述成“唯一联系只有一个简报 URL”。本轮 Workflow 无需运行即可查图和打开资料。
- 模型只经 ModelPort 注入；此轮替换模型核心未改 tools/services/database。工具共享基础设施及领域服务是明确依赖，不等于工具相互调用编排。
- 当前服务装配仍含字符串键 service bag，存在类型可读性改善空间；本轮无证据表明需改成多层通用插件框架。
- `tests.xml` 的 138 项覆盖真实 PostgreSQL 并发/事务/锁超时/租约、取消后禁止提交、已提交回执恢复、知识只读角色、工作区失效、旧资料导入隔离、原生/JSON 本地协议、SSE 重连等。`architecture-routes-tests.xml` 另 21 项检查架构与路径规则。
- 授权守卫校验用户消息来源、逐字引用、非导入消息、事务和版本；**不会理解自然语言授权意图**。朋友/假设/否定意图由模型结合原话判断，第一视角已验证正常决策，不声称工具能阻止任意失控模型拿一句真实原话授权任意写入。这与总纲“不在 harness 判断业务意图”一致；不以关键词黑名单或每次固定确认替代模型。

### 两个需要修复的缺口

**A｜未解析会籍汇总口径错误（数据契约，中优先级）**

- 实证：`memory/request-005.json` 同时存在 1 条未解析 holding 和 `coverage.unresolved_holding_count=0`，且 omissions 正确声明 unresolved_query_sources。
- 原因：`services/route_query.py` 先在 UserData/身份层解析，再用 `use_saved_holdings=False` 调用知识 RouteService；后者自身计数不含服务层已经分离的未解析 holding。`tools/routes.py::scope_coverage` 只补 omissions，未统一数量。
- 影响：模型/UI若依赖汇总数字会得到矛盾信息。本次没有生成虚假路线，但不能视为正确合同。
- 改法：在 RouteQueries 返回的完整结果边界统一未解析来源与 holding 数量，明确两者定义；search/page/inspect/waiting 都沿用同一口径；补“部分已解析、部分未解析”的真实 PG 合同断言。
- 对齐：agent-context-and-memory 的 Unresolved holdings stay usable memory；independent-agent-tools 的有范围结果返回。

**B｜比较表遗漏展示角色（展示一致性，中优先级）**

- 实证：`routes/response-007.json` 请求角色，`request-008.json` 回执保留，`browser-workspace.txt` 的比较表无主选/备选；`workspace_v3.js::renderPresentation` comparison 分支没有消费 block.roles，其他图卡分支消费了该字段。
- 影响：模型依据成功回执说“主选已展示”，用户只看到顺序；第一视角与第三视角结论不一致。
- 改法：比较表名称单元明确呈现已校验角色，并验收 DOM 与回执一致；不让前端重新评分或替模型推荐。
- 对齐：model-owned-presentation 的模型拥有选择、真实渲染与回执；display.present 明确承诺 order/roles/columns。

## 未覆盖与阶段判断

23 个完成对话覆盖了主要数据交互和高风险边界，不能证明穷尽所有自然语言或所有网站/数据规模。未执行第三方模型完成率、真实计费 token、生产切换及真实实时网络断线恢复；SSE/崩溃/并发边界以本地 fixture 和真实 PostgreSQL 测试覆盖，不能冒充人工逐个线上断网试验。

原方案保留的 7 项第三方模型验收仍待用户审核授权。建议先修 A/B，再按优化方案验收上下文变更；本次结果不足以宣布整个 change 无缺口完成。

诊断脚本本身曾出现两次已解释的操作者问题：统计工具数量时把故意未知工具也纳入 12 工具断言；恢复驱动首次经 heredoc 子进程启动导致 stdin 类型不适用、尚未开始运行。分别修正统计口径/改为直接 PTY 启动，未改产品代码或放宽验收标准。
