> 当前实施顺序与授权边界以 [实施总纲](charter.md) 为准：先完成系统侧人工双视角验收与本地架构收口，交用户审核；审核明确允许后才调用第三方模型 API（含探针）。原真实模型验收项保留待执行。

# 模型输入视角审查（2026-09-08，持续更新）

## 方法和边界

按六项 specs、design 及全部规范附件对照当前实现。先静态审查，再由开发助手替代 ModelPort，逐次读取真实投影后的 messages/tools 并选择下一调用；执行的仍是真实 Harness、工具和隔离 PostgreSQL。业务模型 API 调用为零，不调用 Workflow、不修改正式知识，不将手动完成算作 G5 模型通过。真实模型验收放在修复和确定性验证之后。

基线清单31/54；已有勾选并非免审。开发助手对“汉莎金”的 Senator 解释是带明确假设的常识输入，不宣称数据库证明该俗称唯一。不能使用仓库中模型未见的数据来组织被测回答。

## 已完成的手动执行

`manual-review-baseline`：独立库 `journeyplus_eval_review_20260908`，来自干净验收模板；5轮、12次人工模型响应。完成 SAS→国泰、汉莎→国泰、SAS全部11路径两页和真实展示回执、皇家约旦inspect、Hilton→皇家约旦不限等级。全部run终态COMPLETED，仅证明这条人工选择的执行轨迹可达，不证明自然模型可靠性、浏览器实际呈现或性能达标。

每次原生格式请求与手动响应保存在私有证据 request-NNN/response-NNN.json；无隐藏思考记录。手动响应时间计入原预算，usage缺失按估算记录，不能算成真实模型token/延迟。第三轮实际展示回执11个ordered_refs，下一请求触发资源提示。

## 发现与需求映射

| 编号 | 发现及证据 | 对应要求 | 处理方向 |
|---|---|---|---|
| R01 | context.py识别effective_query并按工具聚合last_metadata；查询历史被突出为近似当前状态，inspect轮却没有对应查询。request-011直接复现 | D1/D2/D6、3.5 | 通用核心不理解业务字段；按原调用保留工具所属摘要，不聚合隐藏任务范围 |
| R02 | 历史对象索引只留ref/path/name，去掉资格、未知、版本和coverage；展示摘要还丢掉ordered_refs。request-009 | storage §3、T03/P02 | 摘要由工具声明，保留状态/覆盖/版本/未知和真实展示顺序；没有合格摘要则保留原配对 |
| R03 | 路线同时classification=MATCH、unknowns=[]、eligibility=UNKNOWN；conditions_complete=false在inspect完整步骤后仍出现。request-006/010 | T3、T03 | 区分查询约束分类、个人资格和概览截断；不改底层算法事实 |
| R04 | 续页status=OK而第一页PARTIAL，coverage仍search_complete=false；四种完整性混用。request-006/007 | T01/A08 | 页读取、图遍历和全库覆盖分别定义；保留相同查询的缺口状态 |
| R05 | IdentityService唯一英文包含匹配直接绑定，违背“substring返回候选”的明确要求 | tools §3、T02 | 恢复精确名/已有别名唯一绑定；词组包含候选带match_basis，交模型选择 |
| R06 | 工具详情统一12KB，没有实现detail24KB的元数据；总批32KB已实现 | tools §1、T03 | 用注册元数据声明投影容量，Harness不按业务操作名分支 |
| R07 | activity.read按名称最多locate50，满50后没有继续定位剩余活动的游标；aspects仅evidence分支使用 | T2/T03、4.1 | 真实集合分页、按明确视图披露，不能把查找上限当全集 |
| R08 | 部分artifact按JSON键拆分、再按文本过滤；sections专用分支已保护原章节，其他资料仍可能分离关联字段 | T03 | 保留原子章节与父对象上下文，明确截断与展开入口 |
| R09 | waiting.update可将旧任务重新置ACTIVE，却只在create检查唯一active | W01/G3、5.5 | update也在同一事务检查其他active任务，冲突保留原对象 |
| R10 | 工具共享ROUTES内部payload结构，知识port提供只读Session而非完全隔离的业务接口；真实数据库只读约束已存在 | D2/D5、I02 | 梳理显式共享对象契约，不引入工具互调/Workflow执行依赖 |
| R11 | 当前提示词重复费用/资格/不补原因要求；“全部不隐含目标”措辞可能覆盖已有用户筛选，与只改明确条件原则有歧义 | D1、2.6/A07 | 修正冲突并收敛原则，不添加品牌/话术流程 |
| R12 | Native schema转换与原DTO不是完全等价，需比较nullable、联合和未知字段；现有错误反馈可纠正但不证明易用性 | S04/T02 | 离线检查真实wire schema、合法/非法参数，保持服务端严格校验 |
| R13 | 旧automation仍引用AgentController/WorkspaceService；G6未执行，不能宣称全仓库已解耦 | I03/G6 | 按切换门槛清理；当前不提前退役旧入口 |
| R14 | 手动三工具调用后因无usage保守估算进入资源收尾；不是实际模型成本证据 | runtime §4、A10 | 分别记录估算和实际使用，不以提高预算代替信息质量修复 |

## 保留的正确边界

通用单循环、独立模型适配、12工具可发现、零工具回答、完整参数才执行、失败回送、写入回执、只读知识事务和版本引用均有现有实现基础。原生Schema和严格DTO、执行状态和业务结论、已显示回执和浏览器反馈仍需分别验收。

网络服务是公开读取/发现，不强制正式路径，不调用模型；新API无原话意图解析。恢复/取消/事务、网络实际站点、浏览器交互沿用明确测试门槛，不用本次人工五轮替代。

## 执行顺序

1. 修复明确违反契约的身份绑定、完整性语义、等待任务冲突。
2. 将业务摘要放回工具边界，Harness只保留原调用及其摘要，消除last_metadata聚合；保护未知、来源、顺序和版本。
3. 补齐渐进读取与详情容量，审查Schema和提示词歧义。
4. 人工模型位置复走只读、条件恢复、详情、授权写入/冲突及长历史；确定性DB/恢复/隔离检查。
5. 所有上述问题关闭后，冻结版本和固定经济模型，最后真实语义验收；通过后才比较效率并完成G6收尾。

不以本审查新增勾选项，不提交Git，不切生产，不将成功片段替代失败记录。


## 本轮修复与验证进度

- R01/R02：撤回有损历史索引和last_metadata聚合，通用context不再识别查询字段；原始调用/结果配对在可容纳历史窗口内保留，超预算整轮移出并提供历史入口。此选择优先保真，不宣称更省token。
- R03/R04：概览截断改为caveats_truncated，inspect返回完整caveats；分类明确仅表示查询约束评价；续页保留原知识缺口PARTIAL。恢复费用scope并为候选补实际活动版本，最后这两项另有34项针对性测试通过。
- R05：包含匹配仅返回带match_basis候选，不直接绑定；模型可用真实候选ref或完整名称继续。未新增品牌别名数据。
- R06：注册元数据决定单项详情24KB预算，批次仍32KB，通用Harness不识别业务操作；用新documents.read测试大章节不被12KB默认上限截掉。
- R07：查找增加可选offset，原调用默认行为不变；Agent固定活动/版本索引后分批读详情。53条已发布活动测试证明可全部读完，首个10条页面只读10份详情。aspects在非evidence视图也展开对应证据。
- R08：长章节片段保留原始祖先字段与path，原活动、版本和来源不因拆块消失；没有改写条件内容。
- R09：update在同一事务检查其他active任务；冲突不改变旧任务，也不新增操作回执。
- R11：取消“全部自动不限目标”的歧义，改为按用户明确范围处理；允许利用仍适用的已取得证据，避免提示词要求每轮重读。
- R12：人工位发现valid_until在原DTO允许null，但native Schema去掉null，使合法“清空有效期”无法表达。移除有损union改写，仅展开本地$ref，保持原Schema语义；协议配置指纹升级。

手动记忆证据：manual-review-memory在隔离库保存未解析名称和日期，相同key回放得到相同operation_ref、revision=1；清空操作因收到Schema不支持null而没有执行，保留为接口缺陷，不算通过。manual-review-null-fixed在修复后先holdings.read，再用真实消息授权和revision更新，回执确认仅日期变null、revision=2。所有这些记录为人工执行，不是业务模型验收；前三个手动manifest未保存源码hash，只凭实际request/response判断输入输出，后续脚本已加入源码hash。

全量：regression-manual-review.txt为821 passed/4 skipped；Schema修复后的regression-schema-review.txt为822 passed/4 skipped/23 warnings（63.88秒）。其后恢复费用scope/版本字段的34项针对性通过。未启动业务模型API；G1–G6真实门槛尚未宣称通过，31/54保持。

尚需继续：修复后的完整多轮/长历史人工复走、独立网络和浏览器检查、正式知识before/after隔离审计，随后冻结固定模型的最后真实验收。R10共享对象结构边界和R13旧链路清理仍在后续任务中，不以文件分开视为完全隔离。

## 后续人工复走（同日）

- `manual-review-scope-fixed` 保留失败：11条候选分5+4+2页；第4次模型输入已禁止工具，因此没有展示。之后人工输入超过45秒，history没有最终正文；迟到输入不能记作成功回答。该记录没有业务LLM调用。
- `manual-review-page-fixed`：分页候选容量从6KB调整至9KB，仍受工具12KB总上限约束，不移除费用scope、未知资格、条件截断或版本。实际7+4页，两个读取、一次展示、一次收尾，默认预算内COMPLETED。展示回执ordered_refs完整11条，包含各步骤的版本简报链接。没有以提高预算掩盖失败。
- 审查脚本改用可取消异步stdin，非COMPLETED立即结束，避免人工超时留下input线程抢占下一轮输入。此为诊断设施，人工耗时不当作模型性能。
- `manual-review-history`：7轮固定对话前缀用于制造超过12条自然消息窗口，随后人工接管。第8轮实际输入已不含最初筛选；通过workspace.read找回原话，执行free_only=true、allow_challenge=false。下一轮只patch free_only=false，实际来源及allow_challenge保持。两次均COMPLETED；UNKNOWN没有被说成已满足要求。固定前缀和人工后续均不算真实模型验收。
- R10：新增共享RouteObject契约，统一验证ROUTES成员类型、workspace范围、完整有序步骤；inspect、activity.read和display复用该契约，工具不互调。只读知识port仍提供SQLAlchemy读事务，是明确的存储适配边界，并非跨数据库服务隔离。错误类型/缺失步骤/跨工作区测试已补；旧控制链R13仍需G6处理。
- 网络实际发现Courtyard Marriott公司页及公开报告137555，读取、独立解析及refresh完成；报告保留原始身份、提交日期和正文，比较结果UNKNOWN。证据network-review-discovery.json、network-review-report.json，不使用OptionMapping或LLM，也不将站点标签MATCH替代正文的挑战条件。
- 浏览器隔离预览已实际展开8→11条路径，顺序与回执一致；点击皇家约旦节点显示对应版本的完整条件，包括加拿大护照限定。发现重复简报入口和部分费用标签易误解，已将相同版本URL去重，并给PARTIAL费用加“已知部分/总费用未知”；正在复验。

最近针对共享对象、上下文、历史和恢复的48项测试通过；完整回归待本轮最终改动后统一执行。原全量822项结果不能覆盖之后的改动。G5真实模型与G6切换仍未通过，不提前勾选相关门槛。

## 首次冻结后真实模型复核与返回人工位

完成前述检查后，仅运行deepseek-v4-flash的A05一次（final-a05-flash-r1），没有扩大64组。自动assertions=[]、五轮COMPLETED，但人工语义FAIL：漏读4条路线、仅看皇家约旦却加入以阿斯塔纳为终点的路线、最后多余澄清、未经证实的联盟原因、将签发证件限制称作国籍限制。5轮17个业务模型请求、180991 input tokens（不含启动探针），不能宣称效果通过。

诊断校正：曾推测旧工具结果挤掉原始SAS金卡消息；按冻结代码复算第三轮投影，原始用户消息仍在，因此该归因撤回。完整结果history策略未因这个误判改写。真实可复现缺口是：收尾仍按携带所有工具schema预留，第一页后禁止继续工具；长网页被通用投影降为索引，模型没有拿到正文。

后续修复（尚须复验，不算A05通过）：
- R14：适配器提供收尾输入估算；收尾不发送工具定义，保留原始调用/结果和名称映射。runtime先判断是否可收尾，再做对应请求硬预算准入；普通请求+收尾分别预留。未提高45k/60k，不按模型或业务分类。无usage的输出估算计入调用参数。
- R15：web.read在原PAGE快照上分页正文和链接；cursor绑定URL/sections/控件读取选项，禁止refresh结合旧cursor，不重复HTTP。满页正文可直接读，不再整段降为index。完整原始HTML保留供research.parse。
- R16：人工读取真实Cathay公司页发现正文混入两组巨大项目下拉选项。选择项中的航司名不是报告证据；默认文字披露排除表单控件，同时返回控件索引并可include_controls显式展开，不删除原文。这属于资料编排质量问题。
- 路线候选恢复显式from/to端点，不仅靠path表达；inspect说明明确不施加新目标筛选，避免“经过该项目”与“终点为该项目”混淆。

manual-review-web-paging完整读取同一PAGE的10822字符及33链接，第二次读取未请求HTTP；人工等待超过45秒导致一次格式修复请求，最终COMPLETED，因此不作性能证明。该次观察暴露表单噪声，控件分离在之后实现。人工结论明确区分入向/出向报告、表单选项及网站未读分页。后续尚需控件分离实际复验和相同模型A05复验。

## R17：第二轮最终 A05 失败及返回人工审查（2026-09-08）

`final-a05-flash-r2`：原始五轮话术、同一 Flash native，22 次业务请求、246394 输入 token，69.7 秒。自动断言为空但人工语义 FAIL，原文件保留，另写 semantic-review.json。11 条路径分页和展示已成功、只看皇家约旦未混入后续中转；仍有把历史第三方报告当当前政策、将结果 Gold Sparrow 当用户目标等级而漏掉 Hilton Gold→Silver Jay、证件条件转述成居住地、路径总结和未知费用表述不一致的问题。没有扩大 64 场验收，也未进入 G6。

修复工具事实契约：inspect/compare 返回所选对象原 QUERY 的引用和完整 effective_query，明确未执行新检索、对象终点不是用户新条件；不修改原 query，不推导 last_query。web.search 改正默认 complete=true/returned=0 的错误，分别记录发现列表分页、报告是否读取、站点是否完整检索；web.read 标明抓取时间不是政策生效日，页面权威性未经验证。没有添加品牌规则、文本纠错覆盖或意图分类器。

人工替代 ModelPort 的真实 PostgreSQL 两轮 `manual-review-query-lineage-r2` 均 COMPLETED：SAS Gold→皇家约旦项目（target.tier_name=null），inspect 保留原查询，再用 query_ref+仅来源 patch 查 Hilton Gold，返回 Silver Jay、49 USD、资格 UNKNOWN。证明工具链支持正确范围，尚不证明实际模型会选择正确参数。首次启动遗漏 PTY，stdin selector 报错；已中止并换新证据目录，没有模型或业务操作。42 项针对性检查通过。

## R18：收尾协议与范围保留

`final-a05-flash-thinking-r1` 未通过：第三轮省略原来源等级，歧义后扩大到所有来源等级（原始金卡用户消息经重建投影验证仍在）；收尾请求删去了 tools，却未发送 tool_choice=none，供应商仍基于历史函数调用发出工具请求，预算拒绝后 PARTIAL。第五轮已正确查询 Hilton Gold→Royal Jordanian Silver Jay，但不能抵消前面失败。完整首次记录和单独 semantic-review.json 保留。

适配器现在显式发送 tool_choice=none；启动 echo 往返的第二步同时验证禁用工具的收尾路径，避免只探测普通调用。单一 instructions 进一步说明“全部路径”不扩大已知来源等级、证件/居住地/国籍不能互换、历史报告不能升级为当前政策。没有业务规则写进 harness，没有追加模型审稿。协议与 runtime 37 项检查通过；后续真实 A05 两次正在独立库执行，仍按实际证据判定。


## 用户审核前系统收口（2026-09-08，本轮最新状态）

本轮遵循 charter.md，全程未调用第三方模型 API。系统改造、人工逐次 ModelPort、真实隔离 PostgreSQL/公开网页/浏览器验收以及旧链退出见 [系统侧审核包](system-review.md) 与 [人工证据索引](manual-evidence.md)。本节更新当前阶段状态，不撤销上文历史失败或默认本机库意外升级披露。真实模型 64 case-run、实际 token/延迟及最终语义硬门槛仍待用户审核明确批准后执行。
