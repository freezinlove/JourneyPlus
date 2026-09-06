# 简报、图、回答展示与 StatusMatcher 详细设计

本文件落实 D9–D11。用户后来的点击收敛和经验第七条优先于早期“线和标签都可点击”的建议。继续现有同仓前端和 FastAPI 部署，不以 React 或新框架为前提。

## 1. 从模型输出到可信页面

模型 ANSWER 仅提交 `{text, blocks:[{type,subject_refs,fact_refs,reason?,columns?}],next_steps:[{label,message,subject_refs}],claim_refs}`。columns 来自白名单，不能是任意 HTML；图节点、费用、URL、日期都由服务端事实组装。自由文字仍需引用语义核对，引用存在不等于断言正确；结构金额与文字矛盾时拒绝该断言并以确定事实反馈。

服务端 Presentation={schema_version:1,id,turn_id,snapshot_ref,text,blocks,next_steps,basis,pending_action,created_at}；block 有 id/type/subject_refs/version_refs/payload。React 与否不是合约内容。普通 JS 对 payload 类型做穷尽分支，未知类型显示兼容错误，不直接渲染模型字符串为 HTML。

数值防漂移采用事实插槽：事实型句子的金额／日期／状态通过 claim_refs 指向已读取字段，服务端填入展示文字；模型生成的比较理由不另设权威金额或 URL 字段。引用不存在、绑定错误方案或数值插槽不符时拒绝该块，渲染已验证事实并说明未能组织完整解释。自由自然语言的语义正确性不能由引用校验完全证明，使用金标和真实模型评测约束，不声称程序能判定全部语言真伪，也不增加第四次审查模型调用。

| block.type | 可信 payload 必需内容 |
|---|---|
| activity_card | activity_ref、title、edition、lifecycle、freshness、target_summary、cost_summary、material_caveats、detail_target |
| route_graph | nodes[{id,program,tier,role:HELD/INTERMEDIATE/TARGET/PUBLIC_OPPORTUNITY,unknowns}]、edges[{id,from?,to,step_ref,route_refs,fee_label,challenge_label}]、routes[{ref,step_refs,role:PRIMARY/ALTERNATIVE/EXPLORE,reason}]、coverage |
| route_comparison | route_refs、columns 白名单、rows 的事实投影与 caveats；不把各未知单元格留空 |
| evidence_answer | answer_state:SUPPORTED/UNKNOWN/CONFLICT、facts、excerpt_refs、source_labels；正文先结论，长证据进详情 |
| experience_summary | step_refs、one_line、research_state、detail_target；通常并入 route 卡，不渲染独立报告瀑布 |
| confirmation | pending_action_id、kind、before、after、support_summary、expires_at、confirm/reject 行为 |
| text | 已净化文字，无虚构来源或申请入口 |

detail_target 是唯一 {kind:ACTIVITY/ROUTE/NODE,ref,presentation_id,version_refs}。除了必要证据引用定位到同一详情的依据部分，卡上不提供另一个“简报／申请／条款”入口栏。

## 2. 页面与事件合同

主对话区始终存在；一个共享详情面板默认关闭。宽屏右侧面板，窄屏占满可用宽度并保留返回位置；不同时打开多个详情。浏览器后退先还原详情／会话位置，不触发模型。

| 事件 | 行为 |
|---|---|
| 点击／Enter 整体活动卡 | 打开相应活动版本详情，并可提示存在更新 |
| 点击／Enter 路线卡 | 展示该路线步骤、适用价格、资格和经验 |
| 点击／Enter 会籍节点 | 同面板展示本次结果中该节点的取得方案；多个方案列为详情内部选择，绝不任选一个 |
| 费用、限制、状态标签和图连线 | 纯信息，无独立链接或研究动作 |
| 展开条款／简报历史 | 确定性资料读取，保留快照和焦点，零模型 |
| 回答末尾下一步建议 | 先在对话显示完整 message + 明确对象，再走 messages API；不能只是改焦点 |
| 确认卡 | 走确认 API，不伪装为普通点击浏览 |

详情顺序固定：概述／当前或历史标识 → 与当前方案相关的费用和资格／时间 → 申请经验（有调查请求时） → 按需依据／历史／原始来源与申请链接。事实未知直接出现，不强迫用户在 Terms 才发现。当前知识变化时旧卡详情仍先显示原引用快照并提示“有更新”，用户刷新后新读取，不静默替换旧结论。

每次 next_steps 默认≤3，按未解关键问题→有意义比较→更多探索的顺序选少量；已经完成的动作不重复建议。自由输入不依赖按钮。无 pending 时不出现通用“确认”按钮。

## 3. 图与比较的数据生成

普通探索按现有有效会籍和直接机会起始，目标分组按 AIRLINE/HOTEL/CRUISE，航司可再按联盟过滤；展开请求带图 snapshot 与 frontier refs。节点按规范项目/等级合并，边以具体 option_version+mapping 区分，平行边可视觉折叠但详情保留全部路线引用。

公开挑战节点标 PUBLIC_OPPORTUNITY，以独立步骤展示，from=null 合法，不创造名为“无会籍”的会籍。窄屏直接把每条精选路线渲染为纵向有序步骤。

推荐图由验证过的 PRIMARY 与至多两条 ALTERNATIVE 的完整步骤并集构建，共用步骤只画一次，替代到达边保留。颜色只能辅助，需文字标首选／备选和原因。未知费用、资格及 partial 必须可见。

比较 columns 允许 COST/CHALLENGE/STEPS/ELIGIBILITY/DEADLINE/VALIDITY/EXPERIENCE/REASON。按问题选择，默认 COST/CHALLENGE/STEPS/关键限制/REASON；无差异且不影响问题的列可省，未知和冲突不能因列省略丢掉 caveat。价格拆币种、费用角色与适用条件；不能合成无意义最低价。

## 4. 简报产品生成

CURRENT 卡无须等待 AI，核心数字从当前知识直接组装；AI 可生成非事实真值的解释文字。UPDATE 比较同活动前后版本，变化类型限 NEW_OPTION/REMOVED_OPTION/PRICE/ELIGIBILITY/CHALLENGE/TIME/LIFECYCLE/CORRECTION。证据增加但语义不变不创建新闻。

UPDATE 内容={title,summary,changes:[{kind,subject_ref,before_fact_ref,after_fact_ref,impact_text}],caveats,source_refs}。金额、日期在渲染时用引用填充；无法判定变化影响就说明变化，不能发明“更容易申请”。新增活动作为首次介绍，与后续更新区分。

一篇文章多个活动各有关联，一活动多篇文章合成一个 CURRENT；第三方补充带来源身份。OTHER 同样提供简报浏览，但路径 API 无该类边。用户会籍关联提示通过相同路径服务确定，不独立生成每用户简报版本。

## 5. StatusMatcher 调查输入和定位

工具 `research_statusmatcher` 输入={step_refs:string[],question:string,refresh:boolean=false}，服务端根据工作区派生 ResearchTarget={step_ref,option_version_ref,activity_version_ref,from_program,from_tier,to_program,to_tier,method,context:{source_acquisition?,residency?,prior_participation?},question_aspects}。不能只传公司名去汇总全站成功比例。

直接问活动经验时，先用活动资料定位可调查步骤；只有来源等级等缺失会影响问题时澄清，不强制先推荐或保存会籍。query 已明确“哪个更稳”可满足用户意图门，但服务端许可开关仍需满足。

项目到公司页映射作为受控配置含 program_id/company_slug/verified_url/verified_at。无映射返回定位不足，可在许可范围内域内搜索定位；搜索仅找列表／报告 URL，不拿搜索摘要当案例。每次按唯一共用步骤去重。

读取顺序：公司列表 → 仅解析 report ID/URL、可见方向和日期用于选择 → 按方向相关、近期优先打开少量详情 → 核对项目等级、两个日期、标签与正文 → 分类。相同 report ID 或规范 URL 去重；公司列表摘要不直接进入结果统计。每个 HTTP 重定向重新检查 host，禁止任意域或内网跳转。

初始同回合最多 3 条聚焦路线、12 个 HTTP 请求（包括跳转和重试）、每公司 2 列表页、总 8 报告详情、单响应 1MB、总 4MB、总网络 20秒截止。流式读到字节上限立即停；队列开始前检查剩余时间，请求 timeout=min(剩余时间,单请求上限)。同回合多个调用共享预算；429 不无限重试，返回可用部分及失败原因。

## 6. 经验记录与判定

ReportObservation={schema_version:1,report_ref,url,submitted_at?:Temporal,application_at?:Temporal,from_program?,from_tier?,to_program?,to_tier?,reported_label?:MATCH/CHALLENGE/DENY/OTHER,normalized_outcome:DIRECT_MATCH/CHALLENGE/DENIED/UNKNOWN,context:有限相关字段,comparability:EXACT/PARTIAL/INCOMPARABLE,reasons:[],notes:[],evidence_excerpt?:string}。notes 仅当前问题相关要点，不保存完整正文。日期未知可为空但必须记录缺失原因。

EXACT 要求方向／双方等级、可确认的申请办法和当前问题关键情境相符；活动期次无法证明一致至少 PARTIAL，项目名相同不能补成同期。关键条件已知矛盾则 INCOMPARABLE；缺失则 PARTIAL。原始名称保留显示，规范化歧义不任选。无需当前问题的字段不强制追问用户。

outcome 以正文支持的实际结果核对标签；标 Match 但正文需挑战时 CHALLENGE，描述相互矛盾时 UNKNOWN 并保留原标签。Deny 不代表官方已关闭。报告申请时间优先判断近12个月，不足才扩24个月；只有提交时间时单列“近期提交、申请时间未知”，不能混入“近期申请”计数。更早只作历史背景。

StepResearchResult={step_ref,activity_version_ref,query_context_hash,observed_at,window,coverage,status,exact_counts,partial_counts,unknown_count,incomparable_count,report_refs,observations,limitations,official_recheck_refs}。已知结果分母只含同类窗口内 DIRECT_MATCH/CHALLENGE/DENIED；UNKNOWN 单列。默认展示计数不展示成功率。返回精确及部分报告数量，模型可说某步骤证据更充分，但不能把数量当审批概率。

各步分别汇总，共用步骤引用同结果；路线级文字说明关键证据缺口，不混池或连乘。不用硬编码“5条就是高成功率”。没有共同可比窗口／情境时不能凭正面报告更多给确定的经验优劣结论。

## 7. 缓存、联动与失败

缓存位于 workspace.state.research，key=方向/等级/option_version/activity_version/相关条件/schema/window 的规范签名；expires_at 不晚于 workspace。相同目标复用已有观察并显示时间。用户补充来源是 MATCHED 时，优先对缓存重新判可比性；需更多资料且用户意图仍包含调查才定向补查。用户显式刷新重新取当前版本和网页。

完整 HTML 只在解析期使用，许可范围内最小结构化记录随工作区到期删除，不加入 document_versions/activity_knowledge_versions。诊断只存状态、字节、请求次数和耗时，避免复制报告正文。

ResearchState=NOT_REQUESTED/DISABLED/UNAVAILABLE/INSUFFICIENT/COMPLETED/PARTIAL。禁用在发请求前确定；零相关报告与超时分别表达；部分步骤成功时保留，失败步骤不沿用旧成功结果而不标时间。无法取得许可时完成关闭和受控样本链路，但真实读取验收明确待完成。

经验提示官方可能存在来源取得限制时，经同一 query_activity_materials 核对；若本回合模型额度不够，返回待核对说明并续接，不能超预算。经验不创建图外机会、不改价格/规则，不把有硬条件失败的路线排成首选。未调查候选保留，并解释比较仅覆盖已查子集。

## 8. 用户认可的第七条如何实现

route_card 的 experience_summary 仅一句，例如“近期可比案例有限，第二步待确认”。整体点击原有路线详情，在同一“申请经验”部分按步骤显示窗口、计数、关键观察、限制和少量 report_refs；原链接从服务端映射。

不增加每报告一张卡、不增加可点经验徽章、不在图中加调查按钮。“再查第二步”“比较申请经验”属于回答末尾的独立下一步消息。依据区来自真实操作，可清楚区分读数据库和刚刚联网。

## 9. 已落地展示边界补充

- 图块显式 `graph_mode=EXPLORE/RECOMMEND`。最终推荐只有一组，程序限制最多三条，PRIMARY 只能给 MATCH；角色跟随路线，按目标折叠后不能每组重新出现一个首选。探索不受三条上限限制，缓存候选不因推荐删减。
- `POST /v2/agent/workspaces/{id}/routes/browse` 接收原 presentation_id、anchor_ref、可选签名 cursor、expected_revision。只读取原查询快照，每页八条；不得把模型资料包预算套在页面后跳过未展示候选。查询版本、会籍或评估情境失效则拒绝续页，原卡不变。
- 浏览投影保存在工作区 `browse_presentations`（最多 24 页，24 小时工作区期限内），拥有独立展示 ID、节点与版本，零 WorkspaceMessage／WorkspaceTurn、零模型／经验请求。同一展开请求幂等。浏览结果参与最近已披露对象的指代上下文，但不伪造对话消息。详情可用这些展示 ID 校验所属关系并更新焦点。
- 浏览器后退首先关闭共享详情，保持原页面和会话位置；主动关闭和 Escape 复用同一历史状态，不能生成 Agent 消息。
- 小型读取凭据含 read_at、已披露版本引用、展示／观察数量、覆盖与停止原因，放在可折叠回答依据中，不展示思维链。资料读取时间不能冒充活动发布时间。
- UPDATE 增加有界前后值投影和影响说明，费用保留目标／币种／角色／适用条件，大型映射及费用前后预览最多六项并列出省略数量，完整值通过版本详情确定性读取。相关原文相同、结构化条件判读不同标为 CORRECTION／INTERPRETATION_UPDATED，不声称官方改变规则。简报生成器升级只重建展示投影，不改已发布事实。
## 2026-09-06 活动来源映射详情补充

独立活动详情中，每个申请办法仅增加一个“来源会籍与对应等级”折叠区；按项目／等级在本次已读映射内筛选，首批20项、继续展开仍在同一面板。每条展示确切来源、目标、可用性及条件／脚注。筛选无结果不推断官方没有机会。已选路线步骤详情只展示对应步骤约束，不重新铺开整个来源表。卡片和节点仍保持一个整体入口，筛选／展开不发送Agent消息、不调用模型或经验网站。
