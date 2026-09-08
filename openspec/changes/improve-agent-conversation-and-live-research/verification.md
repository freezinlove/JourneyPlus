# 最终实施与真实验收记录

日期：2026-09-07。Change：`improve-agent-conversation-and-live-research`。

**最新结论见文末“通用路径交互复验”。前一轮整体通过判定覆盖不足；其具体回放作为历史证据保留，不代表当时已经覆盖已有会籍的不限目标请求。**

## 范围与环境

实现和验收均使用当前工作区代码。真实模型为百炼 `deepseek-v4-flash`，常规 Agent 请求显式 `enable_thinking=false`，预览实际 IO timeout 45秒，整轮预算90秒；没有改变 AIWorkflow 的默认 thinking 策略。

真实 PostgreSQL 副本为 `journeyplus_eval_journal_writes_20260906_133215`，仅该副本升级到 `0025_agent_delivery_events`。预览为 <http://127.0.0.1:8769/workspace>，通过统一 `build_researcher` 显式开启 StatusMatcher。正式库、正式开关、发布及 Git 提交不在本次执行范围，均未操作。

本报告区分三类证据：真实模型/HTTP/数据库回放、浏览器操作、确定性契约与故障注入。后者不冒充真实外网故障或生产验收。

## 完成度与规格对应

| 规格要求 | 实现及验证证据 | 结果 |
|---|---|---|
| Natural grounded conversation | `agent/narration.py`、`workspace.py`；A三次完整回放、资格追问、未知价格否定表达 | 通过 |
| Explicit unrestricted task scope | `task_context.py`；B三次完整回放及追加不限/单目标变体，假设空起点不读取存量会籍 | 通过 |
| Grounded presentation references | `display_focus.py`、`material_references.py`；真实“第二条贵在哪里”、点击节点后问证件、零模型浏览 | 通过 |
| Bounded efficient reads | `knowledge/packets.py`、路径缓存；真实181候选分页、越航超大资料降级保留目录身份 | 通过 |
| Explicit model parameters and measurements | `ai/provider.py`；参数隔离、失败耗时、真实usage及流式首输出 | 通过 |
| Recoverable verified streaming | `delivery.py`、0025迁移、`workspace.js`；真实断开订阅再续接、页面刷新、截断/过期故障测试 | 通过 |
| Real conversational acceptance | 41轮主回放及8轮专项、总调用/tokens统计、失败记录保留 | 通过 |
| Verified live research wiring | `live_research.py`、CLI和预览共用装配；真实列表和报告读取、UI来源链接 | 通过 |
| Honest research scope and failure | 区分未定位/未配置/HTTP/解析/无案例/不足可比；复查实际0新增HTTP、临时缓存 | 通过 |
| Real end-to-end evidence | 加航75K→越航白金真实案例，另以加航50K→皇家约旦核对不足可比结果 | 通过，范围限制见下文 |

## 真实对话与业务结果

主回放记录为 `.secrets/agent-repair/final-accept.json`（41轮）。A、B分别完整连续回放3次，不是独立问题拼接；最后一版主回放无执行错误、无结构化解析中断。新增单目标/未知费用/不限变体记录为 `final-variants.json`（8轮）。模型自然措辞会有变化，按实际业务含义验收。

- A：正常问候；皇家约旦 Gold Sparrow 为149美元、批准后12个月；假设加航50K的路线可绘制且不写会籍；下一轮回答证件签发国家、Royal Club编号、参与历史、姓名一致、加拿大护照要求，申请时间/时区留待查来源，区分用户资料与来源缺口。资格追问1次模型调用，未复述路径模板。
- B：第一轮执行公开入口查询；“所有都行／任意都列／酒店和航司都要”继续同一范围，不再强制询问品牌。当前副本未发现已核实公开入口，回答保留资料覆盖不完整，不宣称市场上不存在机会。保存会籍3次均产生待确认卡，随后取消，未写会籍。
- 限定 Royal Jordanian 的公开查询保留单一目标。越航白金“是不是免费”保留“尚不能确认免费”的直接答复，没有将未知费用当零。
- 实际 PostgreSQL 价格状态复核：当前版本18项已知、17项未知；历史版本另计，不混为当前状态。
- 在真实副本使用全部已知加航起点进行分页压力验收：181个候选，23页（22×8+5），没有遗漏或重复；每页模型包测试上限3000字节，实际1020–1394字节，完整对象仍在服务端。`searched_published_graph_complete=true`，但知识缺口使 `search_complete=false`，没有夸大覆盖。
- 真实会籍确认幂等验收：同一确认请求调用两次，首次业务日志+1、重试+0，结果revision相同；测试事务最终回滚，业务状态恢复，待确认卡随后取消。证据 `confirm-accept.json`。

## 浏览器与流式

在浏览器实际点击发送，立即看到已收到及禁用发送；阶段随真实目录/路线/研究/正文处理切换。新增“已用N秒”；完成后“回答依据”展示模型处理和资料读取耗时，避免只能看到总等待。

- 双目标比较后问“第二条贵在哪里”，正确指向越航白金并说明费用未知，未把未知当更便宜或编造差价。
- 点击皇家约旦节点后问“这个要什么证件”，直接读取点击对象所属步骤，未再答越航条件。卡片/节点各一个主入口，详情包含该步骤的活动简报及来源。
- 数据库审计点击前后：消息8→8、模型调用8→8、研究HTTP0→0，仅focus/revision更新（`browser-before.json`、`browser-after.json`）。
- 点击“调查匹配经验”生成可见用户消息，再读取真实外站；研究结果附着对应步骤，点击卡片查看案例，来源链接确认为 `/report/110879`、`/report/136966`。
- 生成双目标比较时刷新页面，最终保留一条用户消息和一个回答，没有重复生成。独立HTTP断线测试在accepted后关闭订阅，重复启动返回同一run，再用after续订；序号无重复、展示块无重复、最终2条消息、2次模型调用。已完成事件流续订为空（`recovery-accept.json`）。
- Provider真实接收content delta；正文按句校验后发布。代表路径首正文约6.3秒，完整结束约7秒；并非将最终全文切块。故障注入覆盖缺少DONE、length截断、已输出后失败、陈旧运行、重复启动和过期级联清理。失败保留正文并明确未完成。
- 更新脚本版本参数，避免旧浏览器模块缓存遮蔽新界面；JSON/思考内容不会作为流式正文显示。

## 性能与模型上下文

同一副本及模型，核心场景至少3次真实重复。下表为整轮，不是单个模型请求；秒数为中位数/最大值。小样本不报告P95。初次请求仍可能命中服务商提示缓存，不将它称作服务商冷启动。

| 场景 | 次数 | 完成秒：中位/最大 | 首正文中位秒 | 模型调用/轮 | 输入tokens中位 | 输出tokens中位 | 总tokens中位/最大 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 普通问候 | 6 | 1.135 / 1.326 | 0.918 | 1 | 85 | 17 | 102 / 118 |
| 费用和有效期 | 3 | 3.737 / 3.891 | 3.518 | 2 | 6162 | 166 | 6328 / 6329 |
| 常规匹配路径 | 3 | 6.979 / 7.211 | 6.330 | 3 | 17047 | 394 | 17445 / 17671 |
| 资格追问 | 3 | 2.484 / 2.703 | 1.161 | 1 | 1008 | 122 | 1130 / 1132 |
| 公开机会首轮 | 3 | 3.753 / 3.903 | 3.040 | 2 | 6246 | 193 | 6439 / 6446 |
| 不限范围续问 | 9 | 1.959 / 2.197 | 1.104 | 1 | 430 | 79 | 510 / 524 |

41轮启动HTTP反馈最大0.022秒；浏览器本地反馈也在1秒以内。切换闲聊需先确定动作时测得3.241秒，略高于普通聊天3秒参考值；不声称所有聊天必定小于3秒。

越航首次研究8.326秒（外网4.799秒、10个HTTP、8个详情）；同工作区复查4.425秒（读取0.050秒、0个新增HTTP，cache_hit=true）。皇家约旦研究10.486秒（外网6.249秒），按复杂外部研究单独报告，未套用普通路径10秒目标。

`metrics-final.json` 保留汇总，每轮 observations 保留各请求实际usage、schema/context字节、HTTP/首内容时间及实际timeout。服务商未返回reasoning/cache分项时保持缺省，不伪造为0；routine请求均显式关闭thinking。历史参数对照：默认7.45/13.07秒，关闭1.77/1.94秒；默认457/875 reasoning tokens。新参数阶段另两次READ为1.656/1.553秒（输入均4876、输出112/106、cached4096）。这些是同场景小样本，不归因所有历史慢请求。

## 真实 StatusMatcher 范围

已复核 company 页面为 air-canada、vietnam-airlines、royal-jordanian-airlines。旧 royal-jordanian 地址的500保留为首次失败证据。

- `/report/136966`：加航75K→越航白金，2026-08-17提交，实际申请日期未知；正文有直接匹配获批描述。身份匹配，但申请方式/活动批次等缺失，所以仅部分可比。
- `/report/110879`：加航50K→越航Gold，2024-11-17提交；对75K→白金不构成可比样本。详情单独标记，不混入统计。
- 加航50K→皇家约旦本次未找到足够可比案例；不将Flying Blue等不同来源报告混算，也不报告0%或成功概率。
- 案例中的359美元、300美元属于自报经历，未写入或覆盖越航官方未知价格。报告提交时间不当作申请时间。
- 有限列表/详情预算产生PARTIAL；没有宣称查遍全站。其余未reviewed项目仍返回未核实映射，不宣称全部可用。
- 普通“再查一次”复用有效缓存；只有明确要求最新/重新联网/不要缓存等才强制刷新，避免模型自行打开refresh造成重复外网读取。

## 失败保留与修复闭环

没有删除失败来制造通过率。`.secrets/agent-repair/` 保留分阶段结果：`public-replay-before-scope-prefetch.json`、`stream-accept-first.json`、`stream-accept-second.json`、`final-accept-before-savefix.json`、`final-accept-before-catalog-fix.json`、`final-variants-before-negation-fix.json`等。

真实回放实际暴露并修复：只查目录就声称完成；不限偏好反复追问；保存时猜ID/重复提议；资格追问复述模板；点击单节点仍回答两条路径；越航大包丢目录后反复读取；聊天编造工作经历；经验回答夹带资格追问；“不能确认免费”被校验误伤；旧模块缓存未加载新版字段；重复研究被模型擅自选择强制刷新。每个相关修复有确定性测试或对应真实复测，不用HTTP200替代业务验证。

历史两次selection_error未保存完整原始动作，无法断言二者都由同一原因造成；本次复现和修复了嵌套价格、evidence_ids的版本所有权缺口，并测试不同版本、目录身份及合并资料包的拒绝行为。

## 验证命令与结论

最终命令：`.venv/bin/pytest -rs`；三个改动JS文件的`node --check`；`openspec validate improve-agent-conversation-and-live-research --strict`；`git diff --check`。

最终全量：**701 passed，1 skipped，23条弃用警告，107.55秒**。三个JS语法检查、OpenSpec strict及git diff --check均通过。常规SQLite测试中仅跳过PostgreSQL发布触发器专项，真实数据库/迁移/回放由上文独立覆盖，不把SQLite跳过项算通过。

浏览器收尾审计：普通复查后HTTP累计20→20（模型7→9次），明确不要缓存后20→30；实际等待显示“资料已取得，正在整理回答 · 已用7秒”，完成依据显示模型4.0秒、读取4.8秒。案例详情可见2024-11-17与2026-08-17提交日期、实际申请未知以及不同可比标签。

规格完整性、业务正确性、设计一致性均按上表核对：21/21任务、10/10规格要求有实现及验证证据，没有未实现的关键项。没有剩余实施阻塞。模型措辞校验是保守的可测规则，不能保证穷尽所有自然语言语义；外站布局及可用性可能变化，正式发布前应继续执行同一验收集。此次不自动归档、不提交Git。

## 重新打开：用户万豪白金对话失败

先前整体通过结论覆盖不足。用户工作区 57abc46e-3f5a-4378-9ea0-24c4dc513e2e 的真实记录显示：中文目录无命中，三次资料读取后兜底错误要求活动；随后 ROUTES/ANY 状态仍追问目标。该场景未验收，不应视为整体完成。原失败保存在 `.secrets/agent-repair/marriott-user-failure.json`。重新打开范围继承与综合验收。


## 通用路径交互复验（替代此前范围不足的整体判定）

本轮不是品牌别名补丁。项目代码中没有新增万豪或其他品牌的专属匹配规则。修正的是目录身份读取、任务完成约束、起点与目标继承、可选字段协议和分页展示链路。

### 已修正的实际根因

1. 中文简称未命中时把目录缺口当成活动缺口；现在 CATALOG 独立于活动存在性，原名/官方名/英文名在一次有界目录读取内去重，返回真实 ID。仅等级名不匹配到名称含该词的其他项目。
2. ROUTES 的 ANY 原来只记状态、不约束执行；现在明确起点与不限目标共同约束查询，旧失败历史的短回复同样要求真实路线评估，ANSWER 不能绕过。真正缺少所属项目仍澄清。
3. 原工具回包没有保留已尝试的搜索词；现在当前回合带工具参数/状态记录，重复无命中目录读取复用，失败搜索词可据此修正。
4. 目标变化偶发被填入起点；现在没有明确来源变更就保留起点，错误参数拒绝执行；独立探索表单的显式选择则按完整表单生效。
5. 可选列表 null 曾引发两次格式重试；工作区协议把这类值按省略处理，必填数据和非法引用仍严格校验。持有某会籍不再等于正常积累取得，本轮数据审计为 UNKNOWN。
6. 全目标正文改为起点、候选总数、本页数量和必要限制的简短说明，详细路径放图。继续浏览跳过已展示的连续前缀，旧图浏览不继承新查询的叙述范围。

### 真实结果

- 六个项目：万豪白金、希尔顿钻石、凯悦环球客、洲际白金、国泰金卡、加航 Elite 50K，共16轮。全部执行实际路线查询、实际起点 UUID 对应所述项目/等级、目标不收窄，续问保留起点；正常结果均流式交付并展示8条首批路径。
- 11轮边界回放：无会籍公开机会、不限续问、闲聊、单活动费用/有效期、仅说明“金卡”、连续切换三种起点、改为皇家约旦单目标、保存/取消。单目标保持凯悦起点；金卡缺项目时只问所属项目，没有猜起点或查询错误路线。
- 原用户失败工作区的完整六条消息及状态复制到新的隔离工作区，保持原失败历史，续问重复3次：均以 Marriott Bonvoy Platinum Elite 实际查询，不再追问目标。原用户工作区和旧错误消息没有被删除或改写。
- 上述30轮经 `.secrets/agent-repair/audit_general_routes.py` 核对真实 PostgreSQL 查询、答案图引用、保存状态及实际调用。会籍记录始终为4条，查询未新增会籍；保存案例仅提议并取消。
- 浏览器实际“我有金卡…”→澄清项目→“国泰航空”→显示17条候选，再继续不限查询和浏览。最新分页为8+8+1，序号1–17无重复、无遗漏，最后没有续页游标；浏览前后消息6→6、模型调用5→5、研究HTTP0→0。

### 观测与保留限制

- 正常首轮8次：总时间中位数6.7505秒，最大7.648秒；整轮输入tokens中位数12938，输出413；3次模型调用，均有真实流式正文。
- 不限续问8次：总时间中位数2.112秒，最大2.498秒；输入tokens中位数501.5，输出94.5；1次模型调用，均有真实流式正文。没有增加独立分类模型调用，没有全库注入。
- 原错误历史恢复3次中，有1次模型先试图用 ANSWER 追问目标，被任务完成检查拦住，第三次调用才读取路线。该次按既有预算兜底输出可读说明和3条首批路径，完整35条候选仍可浏览；**此轮没有额外流式模型正文，不计入正常流式通过样本**。其余2次恢复正常流式显示8条。三次均完成实际路线查询，而非把格式合法当作完成。
- 小样本、同机实测，部分与自动回归并行，不宣称统计P95。当前已发布知识覆盖仍不完整，35/17/41等数值是本次资料中的候选数量，不代表全部实际机会或个人申请资格。
- StatusMatcher 本轮未修改研究适配器，沿用前述真实接入验证及项目映射限制，不扩称全站可用。

### 最终验证与证据

- 全量：716 passed、1 skipped、23 warnings；跳过项仍是SQLite不具备PostgreSQL发布触发器，警告为原有兼容/弃用警告。
- JS语法检查、OpenSpec strict验证、git diff --check通过。
- 证据：`general-route-accept.json`、`general-route-boundaries.json`、`general-route-recovered-history.json`、`general-route-final-audit.json`、`browser-general-pagination.json`、`browser-general-final-before.json`、`browser-general-final-after.json`、`general-route-full-tests-final.txt`，均在 `.secrets/agent-repair/`。
- 原截图失败、跨项目目录循环、等级误命中、起点/目标颠倒、null列表错误和旧历史ANSWER绕过的修复前记录分别保留为 `marriott-user-failure.json` 与 `general-route-before-*.json`，未覆盖删除。
- 预览8769已加载最终代码；正式数据库、生产开关和Git提交未操作。所有改动保留在工作区，未归档change。

## 指定目标下补齐起点：用户报告后的修复验收

本节为本次范围继承问题的最新结论；前述全目标验收不能覆盖“所有到指定目标的路径”。保留原始失败工作区 `8b1b7707-e3bd-4093-afe7-4d5cc2bb20e7` 的只读快照 `target-clarification-user-failure.json`。第二轮真实模型已提交 Cathay 的目标引用，后端却因 ANY 清空目标；这是实际执行范围错误，不只是文案错误。

修复了范围关键词抢占语义、未提供字段覆盖已选范围、起点澄清丢上下文、目标执行缺乏约束、等级检索通过 alternate_names 凭空引入项目、未定位起点回退存量或展开多个候选身份。没有汉莎或国泰专用业务分支。后续复测还暴露“目标不限”被旧 SELECTED 保留的问题，增加明确重置与一般“所有结果”分离的校验。

真实验收（隔离预览、实际 deepseek-v4-flash、实际 PostgreSQL）：
- `target_clarification_live.py` / `target-clarification-live.json`：22 轮，三组原始问题各接“汉莎金”→明确 Senator→“所有都要”；另含 Hilton/Royal Jordanian/Vietnam、英文、全目标起点补充和单句指定目标。
- `audit_target_clarification.py` / `target-clarification-audit.json`：15 轮真实路径查询、7 轮必需身份澄清；逐轮核对实际起点和目标目录 UUID、单一起点、不合并已存会籍、UNKNOWN 来源取得方式、图中起终点。所有核对通过。当前隔离库 Senator → Cathay 无命中，另直接调用 RouteService 复核为空，未以其他目标补结果。
- 全目标取消后保留 AIRLINE 类别；“所有都要”保持既定 Cathay。已保存会籍数量仍为 4。
- 22 轮本地样本整体中位 6.4365 秒、最大 8.057 秒，输入 tokens 中位 14601.5；包含澄清、查询、兜底与普通续问，且测试有并发负载，不能当作 P95 或性能保证。
- 真实浏览器工作区 `e12118a3-cf79-4c33-a4c7-7d3d2e295e21`：指定 Cathay 时无其他航司图；明确取消目标后显示多航司图。DB 证据 `target-clarification-browser-unrestricted.json` 确认仍为 Senator、target_program_id=null、category=AIRLINE。
- 全量回归 734 passed / 1 skipped（PostgreSQL 发布触发器不在 SQLite 测试执行）。随后补充独立类别继承测试及小修，相关 workspace/route_browsing 共 80 passed。OpenSpec strict、git diff --check 通过。

边界与失败保留：单个简称仍可能需要澄清规范等级；少数三次调用用尽的回合为确定性简短结果、没有额外模型流式正文（全目标兜底首批可为 3 条，完整候选仍可浏览）。自然正文仍可能冗余或附带不必要的邀请，不据此宣称全部对话质量已解决。失败迭代分别保存在 `target-clarification-before-source-guards.json`、`target-clarification-before-scoped-prose.json`、`target-clarification-before-rank-origin-fix.json`、`target-clarification-before-explicit-reset.json`，未混入最终通过矩阵。所有证据位于忽略目录 `.secrets/agent-repair/`；原用户历史未改写，正式库、正式开关未修改，无 Git 提交或归档。

最后类别继承小修已在重启后的真实浏览器继续验收：“还是只看国泰航空”恢复 Cathay 目标，仍保持 Senator 起点、AIRLINE 类别、不合并已存会籍，新回复不包含其他终点图。实际 DB 记录见 `target-clarification-browser-final.json`。预览 `/workspace` HTTP 200。

## 2026-09-08 用户实测：起点和目标切换首次生效

只读保存原工作区 `fd516361-c1cb-4315-8a18-f8e49b5a359b` 六轮原话及调用历史，证据 `switching-user-failure-20260908.json`。第 3 句“汉莎金呢”实际仍查 SAS→Cathay；第 5 句“那把 sas 所有匹配路径都给我”已标记更换起点却实际仍查 Lufthansa→Cathay。不是缓存显示问题，旧执行条件确实未被正确更新。

最终实施为小型查询修改计划、规范目录检索、仅选择改变身份、后端合并执行、真实结果流式表达。KEEP 字段由后端保留，不依赖模型复写旧 ID。补充未解析身份的跨轮检索信息、目录等级别名、复合名称有界查找、过多同义检索词去重裁剪及表单入口清除旧对话计划。完整设计见 design.md 最后章节。

真实验收：
- `switching_live.py` / `switching-live-20260908.json`：25 轮，原始六句完整重放两组、删除纠正句后的五句连续切换、不同品牌及目标切换、裸等级澄清和“所有都要”保持目标。
- `audit_switching.py` / `switching-audit-20260908.json`：22 轮实际路线查询和 3 轮必需起点项目澄清全部通过。逐轮验证起点项目、精确等级、目标项目 UUID、未擅加目标等级、单一起点、图中所有起终点、无不完整任务及至多三次调用。汉莎按 Senator 验收，不能只认项目对就算通过；SAS 恢复为 GOLD，全目标 23 条候选。当前库至 Cathay 无命中，未以其他目标填充。
- 本批耗时中位 5.024 秒、最大 7.074 秒；实际 provider 累计输入 tokens 中位 3050。仅为本地有限样本，包含澄清和不同结果量，不构成延迟保证或与此前不同批次的严格性能对照。
- `switching_other_live.py` / `switching-other-tasks.json` / `switching-other-audit.json`：5 轮实际模型及数据库回归通过。费用问答为 149 美元、批准后 12 个月；退出会籍话题不读业务资料；指定 Air Canada 75K→Vietnam Platinum 的 StatusMatcher 调查实际发出 10 次 HTTP 读取，返回 PARTIAL 和部分可比样本，不包装为完整成功率。
- 全量回归 747 passed / 1 skipped，跳过项为 SQLite 环境不执行的 PostgreSQL 发布触发器；JS 语法、OpenSpec strict、git diff --check 通过。

身份目录数据：隔离预览库按 [ITA Airways 官方 Miles & More 卡面说明](https://www.ita-airways.com/us/en/profile/miles-and-more) 登记了 9 个带来源的等级别名：Senator 的 Gold/金/金卡，Frequent Traveller 的 Silver/银/银卡，HON Circle 的 Black/黑/黑卡。这是卡面称呼映射，不是联盟资格推导；HON Circle 也有 Star Alliance Gold 权益，不能把联盟 Gold 唯一等同 Senator。脚本 `register_verified_tier_aliases.py` 与 `verified-tier-aliases.json` 保留实际变更。正式知识库未写入，用户 holdings 数量仍为 4。

限制如实保留：22 轮查询中 21 轮提供真实流式正文；“只看皇家约旦航空”有一次模型返回空的必填检索列表，格式修正占用预算，随后实际查询正确并展示图卡，但正文走了非流式简短兜底。本次不把它算成流式通过。自然表达仍偶有“直接匹配”、多余邀请或要求不必要信息等措辞问题；本节证明的是首次切换的实际执行正确，不声称全部自然语言质量已彻底解决。

失败迭代分别保存在 `switching-before-turn-plan.json`、`switching-before-bound-resolution.json`、`switching-before-alias-validation.json`、`switching-before-required-lookup.json`、`switching-before-compound-lookup.json`、`switching-before-synonym-bound.json`，均未混入最终通过结果。证据位于忽略目录 `.secrets/agent-repair/`。用户原始对话未改写，无 Git 提交、生产开关变更或正式发布。

更新后的 8769 预览另做真实浏览器三轮验收，工作区 `852a8f45-1116-4916-9bae-e31d1c1709e6`：SAS 金→国泰，首次“汉莎金呢”执行 Senator→Cathay，首次“那把 sas 所有匹配路径都给我”恢复 SAS GOLD→不限目标，显示 23 条候选、本页 8 条及关系图。逐轮原话没有增加“我是说”纠正；`switching-browser-hans.json` 和 `switching-browser-final.json` 保存对应实际 query 与消息。8769 已重启加载最终代码，独立 8772 验收服务随后关闭。
