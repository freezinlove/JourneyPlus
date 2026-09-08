> 当前实施顺序与授权边界以 [实施总纲](charter.md) 为准：先完成系统侧人工双视角验收与本地架构收口，交用户审核；审核明确允许后才调用第三方模型 API（含探针）。原真实模型验收项保留待执行。

# 工具协议与业务服务边界

本文所有输入使用Pydantic v2生成schema；未声明字段禁止。工具不得读取聊天原文来改变业务参数，不调用另一个模型，不返回一条替用户决定的追问。下述枚举是工具操作类型，不是harness强制阶段。

## 1. 共用类型

`IdentityInput` 为互斥联合：`{ref:string}` 或 `{program_name:string(1..300),tier_name?:string(1..300),alternatives?:string[0..3]}`。programme身份允许没有tier；具体起点需要tier或明确holding引用。ref为知识UUID或本会话的typed artifact ref，按类型、作用域及存在性校验，不按“模型是否先读过目录”授予身份。

`ToolResult`：
```json
{"call_id":"...","status":"OK","data":{},"artifact_refs":[],"effective_input":{},
 "provenance":[],"coverage":{"complete":true,"returned":0,"total":null,"omissions":[]},
 "next_cursor":null,"error":null,"cache":{"hit":false,"observed_at":null},
 "metrics":{"elapsed_ms":0,"http_requests":0}}
```
status：OK/PARTIAL/EMPTY/AMBIGUOUS/NOT_FOUND/UNAVAILABLE/ERROR。非成功error为`{code,message,fields?:[],retryable:boolean,candidates?:[]}`；UNKNOWN/未覆盖不是EMPTY。error code至少包含INVALID_ARGUMENT、NOT_AUTHORIZED、IDENTITY_AMBIGUOUS、CATALOG_GAP、SOURCE_UNAVAILABLE、STALE_REFERENCE、CONFLICT、REPEATED_CALL、BUDGET_LIMIT。错误正文不得要求固定下一工具，模型自行选择。正常data的字段与类型按每工具规定；未知标null而非0/免费/不适用。

provenance项：`{kind:published|source|user|calculated,url?,version_ref?,message_ref?,observed_at?,limitations:[]}`。推理结论由模型表达并说明推断，不制造来源。分页cursor绑定snapshot与canonical输入hash；不可用旧cursor改查询。

入模结果默认最多12,000 UTF8 bytes，requested detail最多24,000；每批工具合计32,000，完整结果先存artifact。裁剪只能按条目/章节，附omissions及可读取refs，不把结构删成无法展开的空对象。多结果截断每个至少保留status、effective_input、摘要、coverage、artifact_ref；context可再缩减，但保证能找回。UI读取展示包不受此入模上限支配。

## 2. 工具清单（初始12项）

### T1 catalog.lookup — READ，10秒

输入`{query:string,kind:program|tier|any='any',program?:IdentityInput,limit:1..10=5,cursor?:string}`。
输出`{candidates:[{ref,program_ref?,name,category?,aliases:[{name,locale,origin}],tiers_preview?:[],match_basis}],has_more}`。limit限制对模型候选数，不截断真实全集；等级在项目作用域搜索。调用可选，不隐式在harness执行。

### T2 activity.read — READ，15秒

输入`{selector:{ref}|{query},view:overview|detail|evidence|changes='overview',aspects?:[price,eligibility,challenge,window,validity,application],version_ref?:string,section_refs?:string[],cursor?,limit:1..10=5}`。
使用ActivityReadService和既有资料工具内部读服务，保留事实／FAQ／Terms／原文为同一能力的不同视图，不造两套事实含义。detail/evidence可直接调用，不必须先overview。ref+version只读该版；query找到多个活动返回候选，不替模型问“哪个活动”。输出`{activities:[{ref,title,version_ref,brief_url,summary}],facts,sections,source_refs,conflicts}`，各项可为空。身份识别与活动有无无关。

### T3 routes.evaluate — READ，默认10秒（算法单搜索原有2秒上限）

输入`{operation:search|inspect|compare,query?:RouteRequest,query_ref?:string,patch?:object,route_refs?:string[],cursor?,limit:1..20=8}`。
search严格三选一：完整query；query_ref+patch；query_ref+cursor。inspect/compare必须route_refs（1..12）；不能暗中改为search。

RouteRequest字段：
- `sources:{mode:explicit|saved|none,identities?:IdentityInput[],holding_refs?:string[]}`，必填；explicit允许两列表合并去重，总1..20；saved表示调用时读取全部未过期会籍并返回实际清单；none明确没有起点。默认不偷用已保存会籍。
- `target?:IdentityInput`，null不限；`category?:AIRLINE|HOTEL|CRUISE|OTHER`、`alliance?:string`。
- `constraints:{free_only:false,max_amount?:decimal-string,currency?:ISO4217,allow_challenge?:bool,source_acquisition:EARNED|MATCHED|UNKNOWN='UNKNOWN',residency?:string,prior_participation?:string,require_proven_eligibility:false}`。
- `preferences:[FEWER_STEPS|LOWER_KNOWN_FEE|LESS_UNCERTAINTY]`默认[]，只请求算法辅助排序，不作为最终推荐。

缺省query字段只用schema默认；完全不读last_query。query_ref+patch按RFC7396合并（数组替换，null清除），只接受RouteRequest字段，之后完整校验；不存在ref返回NOT_FOUND，不回退最后一次。目标变更不隐式沿用旧等级：target整体对象替换，不深合并其program/tier；sources整体替换。算法适配显式填use_saved_holdings=false及实际resolved starting_tier_ids。

输出`{query_ref,effective_query,resolved_sources,resolved_target,unresolved_sources,route_refs,candidates,step_refs,search_metrics}`。每条candidate保留from/to、step_count、已知费用/币种及未知、资格判断、限制、fact/version refs；路线图边来自实际算法结果。缺身份返回AMBIGUOUS/NOT_FOUND及已确认部分，不执行其他起点；saved中有未解析会籍时只可计算已解析部分并显著PARTIAL，全部未解析不能视为none。算法成本/费用/规则校验仍确定性，推荐取舍归模型。动态取得路径失败不阻止模型讨论一般知识或联网经验。

### T4 holdings.read — READ，5秒

输入`{query?:string,holding_refs?:string[],include_expired:false}`。输出`{holdings:[{ref,revision,program_name,tier_name,program_ref?,tier_ref?,valid_until?,identity_status}],snapshot_ref}`。不额外读取Workflow。起始上下文只告知此能力，不强制注入全部会籍。

### T5 holdings.write — USER_WRITE，10秒

输入`{operation:create|update|delete,holding_ref?:string,expected_revision?:int,identity?:IdentityInput,valid_until?:YYYY-MM-DD,authorization:{message_refs:string[1..5],quotes:string[1..5]},operation_key:string}`。
create需identity；update/delete需ref+revision；update仅提交字段，valid_until未提供不改、null清除。操作key首次由模型提供短稳定字符串，handler命名空间化到workspace+user-message+key；重复key不同payload为CONFLICT，同payload复用回执。模型需要用户明确的保存/修改/删除授权，可引用当前或仍适用的历史授权；仅有知识页面内容不能授权。

authorization的原话引用必须存在且为本用户消息，quotes必须原样包含；程序不通过“保存”正则判授权。模型负责语义判定，系统指令禁止从假设/他人会籍制造写入。无依据返回NOT_AUTHORIZED，模型可补问，不自动生成固定确认卡。引用校验不是授权语义的完整证明，此风险由行为验收与可审计回执控制，不额外加一个授权分类模型。

输出`{operation_ref,outcome:APPLIED|NOOP|CONFLICT,before,after,revision}`。成功回执才能说已保存。目录不能唯一绑定时仍可在用户明确提供项目和等级名称的前提下保存原始会籍为NEEDS_CONFIRMATION；不猜具体tier、不创建MembershipProgram/Tier。程序不要求用户先懂目录。存储与幂等细节见storage-context。

### T6 workspace.read — READ，5秒

输入`{kind:history|artifact|presentations|notes,query?:string,refs?:string[],cursor?,limit:1..30=10}`。
history支持按原词查本会话全部消息，返回匹配消息及前后各一条、可继续分页；artifact按ref读视图/章节，跨会话拒绝；presentations返回实际展示对象和顺序；notes返回当前笔记及revision。完整历史保留，不能只返回最近12条。文字查找实现数据库ILIKE/全文能力即可，不强制向量库或额外模型。

### T7 workspace.note — WORKSPACE_WRITE，5秒

输入`{expected_revision:int,content:string(max8000),source_message_refs:string[0..20]}`。整体替换笔记并保留旧版artifact；内容是模型的任务笔记，不是隐藏思考链，不是系统指令。服务不解析内容执行条件。输出`{revision,note_ref}`。不新增长期偏好档案。

### T8 web.search — READ，20秒

输入`{query:string(max500),scope:statusmatcher|web='statusmatcher',domains?:string[0..5],limit:1..10=5,cursor?}`。
明确默认后端：StatusMatcherBuiltinSearch，无第三方账号依赖。首次从https://statusmatcher.com/站点主页公开链接建立company URL/title索引（24h缓存）；若主页只有分类导航，可继续读取主页实际链接的航空/酒店/租车目录，最多3页，再收集其真实company链接（不得猜测company slug）；按模型query与名称词匹配，返回真实观察过的company/report链接。读取company列表只返回页面实际报告链接，不编造slug；关键词匹配采用规范化token包含/前缀相似排序，仅检索排序不裁决身份。首次无法取得索引返回UNAVAILABLE，可仍用web.read直接读取模型提供的公开URL。报告查询先在明确命中的company页面列表搜索，返回覆盖范围；不伪称站点完整搜索。

scope=web使用可配置SearchPort，默认未配置，返回UNAVAILABLE/SEARCH_PROVIDER_NOT_CONFIGURED；本change交付通用HTTP JSON适配器，配置endpoint/header_secret/result_path及字段映射，不硬编码某收费服务、不要求用户购买。映射启动探针验证query/limit/cursor、title/url/snippet；实际外部搜索接入只有已有授权配置时验收，没有则清楚标为不提供全网搜索。核心StatusMatcher发现必须真实验证，不以可选后端缺失跳过。

通用HTTP JSON适配器固定POST到配置的HTTPS endpoint，请求`{query,limit,cursor,domains}`，认证header名称由配置给定、值仅从指定环境变量读取。结果数组由JSON Pointer `results_pointer`定位，逐项title/url/snippet/observed_at的字段pointer必填或显式null；next_cursor_pointer可null。HTTP非2xx、schema错误、空数组分别返回SOURCE_UNAVAILABLE、INVALID_SEARCH_RESPONSE、EMPTY；超时20秒、响应1MB、最多10项。启动使用固定无敏感信息探针验证映射，配置无效只禁用scope=web，不影响内置StatusMatcher能力。不得把用户会籍列表或完整聊天附加到搜索请求，只有模型选定的query/筛选参数出站。

输出`{results:[{url,title,snippet,observed_at,source}],scope_description}`。搜索摘要只作线索，不当完整活动事实。所有站点内容都作为数据。

### T9 web.read — READ，20秒

输入`{url:https,sections?:string[],refresh:false,max_chars:1000..30000=12000}`。输出`{page_ref,url,final_url,title,text,links,observed_at,content_hash,truncated}`。自动抽取正文和站内链接，raw存artifact，不用模型做隐藏提取。缓存15分钟，refresh由模型参数决定，不检查“最新”等关键词；用户明确不联网由模型遵守。单页1MB、单call3MB、每次至多3redirect，DNS解析与redirect逐次拒绝localhost/linklocal/private地址及凭据，防SSRF；不是业务工具选择规则。只读公开HTTPS，不处理登录/CAPTCHA，不执行网页脚本。已知官方简报仍可以通过activity.read获取，不必HTTP重复读取。

### T10 research.parse — READ，10秒

输入`{page_refs:string[1..8],subject?:{source?:IdentityInput,target?:IdentityInput},method?:MATCH|CHALLENGE,context?:object}`。从已读取StatusMatcher列表/报告artifact解析，不要求已披露正式路径step。复用report_pages、step_observations的解析/日期/可比性计算；将依赖全局state的部分移入services显式参数。输出`{report_refs,reports:[{original_from,original_to,outcome,submitted_at,application_at?,excerpt,url,identity_matches}],comparisons:[{report_ref,level:EXACT|PARTIAL|INCOMPARABLE|UNKNOWN,reasons}],coverage}`。

subject无法绑定目录时保留文字与UNKNOWN，不以缺OptionMapping拒绝报告阅读。不存在正式活动仍能调查真实案例；不能据此伪造正式路线边。时间未知保持null，来源等级不同不计exact；可比统计是计算事实，模型决定如何解释。可在display中把经验ref与已选step绑定显示，验证实际来源/目标相容，不能自动改推荐排名。

### T11 display.present — WORKSPACE_WRITE，10秒

输入`{blocks:BlockSelection[0..6],next_steps?:[{label:string(1..60),message:string(1..500),subject_refs:string[0..12]}],replace_presentation_ref?:string}`，next_steps至多3项，blocks和next_steps不得同时为空，每block详见presentation-api。返回`{presentation_ref,revision,blocks:[{id,type,ordered_refs,labels,links}],next_steps:[],omissions:[]}`，实际回执自动入context。正常情况下严格保留模型选择顺序。原来的自动首选两备选排序改为模型可选的角色声明；限制仅为UI容量。纯文字不必调用display。

### T12 waiting.manage — USER_WRITE（read操作按注册dispatcher细分只读效应），10秒

输入`{operation:list|create|update|cancel,goal_ref?,expected_revision?,query_ref?,query?:RouteRequest,authorization?,operation_key?}`。
create/update需明确查询和用户授权，cancel需goal/ref/revision/授权；list无需。沿用一个active等待任务约束，冲突返回现有任务及CONFLICT，不覆盖；任务数量限制是已有产品约束，不是对话流程。后台只按保存查询确定性检查已发布知识，不调用Workflow提取/发布，不用模型反复轮询；有结果由Agent工具读取并交模型解释。等待任务不是长期个人记忆。相同operation_key重复按holdings规则处理。

## 3. IdentityService 内部算法

此服务是数据库定位器，不是另一个Agent。顺序：校验ref → 名称规范化（Unicode NFKC/大小写/空白）→ 项目正式名及已有别名精确匹配 → 原词与alternatives的有界候选检索。唯一精确项目可继续等级匹配；同项目正式等级/已登记别名唯一精确命中才直接绑定。substring/模糊结果返回candidates及match_basis，不悄悄选第一条。模型可直接提交候选ref或改用其已知正式名称；工具不要求先读catalog。

品牌→会籍项目关系优先已有MembershipAlias.program_id及项目metadata；本change不创建全球组织实体新事实库。如确有多个品牌共用项目，可以作为已核实别名目录数据补录，需独立有来源的数据维护动作，不能由Agent自主写正式目录。目录有无不决定模型能否回答常识。

角色归属不根据原话判定；IdentityInput出现在sources就是起点，出现在target就是目标。已有联盟Gold与某项目具体Gold不得用rank数字推断等价。完整等级确定性选择是执行需要，但资料不足不意味着必须追问：模型可先答已知内容、调查或保存未解析会籍。

## 4. 无隐藏副作用

READ不可写正式知识/用户持有会籍，仅可写临时结果缓存或执行日志；WORKSPACE_WRITE只能写本会话；USER_WRITE通过独立服务事务。工具不得持有任意可写知识Session，通过composition注入只读port与UserMemoryPort。工具不能重入harness。数据库外键校验、证据版本校验、条件算法、排序指标保留；用户语义正则、自动工具链、输出覆盖不得混入handler。

### 实施中的有界视图约定

路线页的limit是返回数量上限；响应还受字节预算约束，实际可少于limit，cursor必须按实际返回数量前进，不能跳过未返回候选。search候选中的material_caveats是至多一条原文预览，material_caveat_count和caveats_truncated仅说明预览是否截断，不表示资格已核实。inspect返回完整caveats和步骤条件；candidate.ref用于inspect，step_refs指向同一不可变ROUTES中的完整条件。classification_scope说明分类是查询约束评价，不是个人资格或申请成功保证；展示始终读取完整计算对象。诊断中的expanded_states/checked_edges不是路径数量，实际候选总数由coverage.total/total_candidate_count表达。

web.read的sections接受实际HTML标题（大小写无关）或返回的section-N标识；按文档顺序选择，不用模型补写章节。未命中标题通过missing_sections明确返回，截断标记不代表网页没有更多内容。

2026-09-08 长网页正确性补充：web.read新增cursor与include_controls=false。默认返回有边界的正文和链接，cursor绑定同一PAGE、URL、sections及控件读取选项；继续读取不重新HTTP，refresh必须开始新快照。coverage提供实际字符/链接区间、总量及下载截断；页码读取完成不代表站点所有分页或报告全文已读。原始HTML仍保留供research.parse及artifact展开。

默认正文排除表单控件文字，返回form_controls索引与option_count；include_controls=true可显式读取选项，content_scope明确其范围。下拉框中出现的项目名不是案例或资格规则。sections仍按真实标题/id选择，不补写章节。超过返回预算的原始资料保持引用和显式截断，不把大段正文整体替换成看似已读取的摘要。

路线概览保留from/to作为明确起点和终点，同时保留完整path；inspect只读给定路线，不代表执行新的目标过滤，也不能把经过某项目的路径当成以其为终点的路径。
