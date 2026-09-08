> 当前实施顺序与授权边界以 [实施总纲](charter.md) 为准：先完成系统侧人工双视角验收与本地架构收口，交用户审核；审核明确允许后才调用第三方模型 API（含探针）。原真实模型验收项保留待执行。

# 实施与验收记录

2026-09-08 开始实施。当前仅基础阶段已进行验证，后续业务与整体验收尚未完成；不以此记录宣称整个 change 完成。

## 基线

- 初始工作区仅本 change 目录未跟踪，无已有源码修改；未经授权不创建 Git 提交。
- 初始源码 Alembic head：0025_agent_delivery_events。
- 旧调用方：product/api.py 的 v1 AgentController；product/knowledge_api.py 的 v2 WorkspaceService/DeliveryService；static/workspace.js 的 v2 消息、确认、焦点、浏览接口；automation/service.py 的工作区清理、两代等待服务及旧 Controller 唤醒。
- 新隔离数据库别名 journeyplus_eval_harness_20260908，源为已有隔离知识库 journeyplus_knowledge_20260905_201603（源迁移为0023）。已记录49张表的计数及内容hash，并升级隔离副本至0025。未启动Workflow，未迁移正式库。
- 私有证据目录：.secrets/agent-harness/20260908/；包含baseline.dump、manifest.json及原始模型/运行记录，不提交个人数据与原始内容。

## 模型协议初验

- 原模型 deepseek-v4-flash，Agent独立HTTP客户端，temperature=0.2，thinking=false，显式配置保守context_window=32768。
- native echo调用和工具结果回送均通过。实际两次请求1266ms/800ms，输入305/371 tokens、输出45/11 tokens。
- 此项仅验证真实原生协议往返；完整JSON契约、恢复、业务工具和64个真实case-run仍待验证。

## 明确的调度拆分实施项

Agent工作区清理和等待检查从Workflow每日编排移出，通过独立Agent维护入口执行；旧Controller等待唤醒随旧控制链退役。对应design D5、任务8.1/8.5/10.3，验收需证明Workflow任务不导入Agent控制器，独立维护不启动采集/发布。

## 真实页面差异与设计补充

首次StatusMatcher验收发现主页当前没有company链接，仅有真实分类导航和最近报告。按已授权独立公开研究范围，补充tools.md：允许沿主页实际分类链接读取最多3个目录页发现company；仍不猜slug、不写正式知识。不属于额外工作流或新增搜索账户。首次NO_REPORT结果保留。

## 持续验收进展（尚未通过 G2–G6）

- 新协议/运行/恢复/API相关确定性测试23项通过；另2项真实PostgreSQL验证通过：并发POST和lease唯一；并发授权保存仅一条会籍和journal；提交后无tool_result的故障窗口仍可找回回执，取消不撤销。
- 新增分页、同数据库快照的草稿和SSE last_seq、启动后过期lease轮询。业务回执独立于临时tool log恢复。
- 浏览器实际完成全日空常识零工具回答；Royal Jordanian卡片展示（首次失败后修复）、详情点击和同版本简报跳转。简报首次误展开变化简报，已改为活动简报并保留无简报说明。
- 保留g2-native、g2-native-retest、g2-native-context、g2-json-comparison、g2-projection-repair、g2-json-role-repair等首次/复测记录。A05曾发生来源目标反转、虚构匹配、误称资料完整；P01曾未实际展示。结构assertions为空不表示语义通过，不能进入切换。
- JSON失败已定位arguments字符串、finished缺失；完善完整输出schema和逐字段错误回送，不把无效调用视为成功。上下文压缩曾删除整项活动，已保留对象和章节引用；增加逐映射/选项的可读资料章节。

## 本机默认数据库意外升级（必须保留披露）

一次验证冻结迁移的命令设置了Alembic sqlalchemy.url，但migrations/env.py随后以Settings.from_env覆盖该值，导致本机.env配置的journeyplus库从0018升级到0026，而非预期journeyplus_eval_migration_20260908。已向用户即时披露，停止对该库写入；未自动降级，未启动Workflow或切换应用路由。

逐个审阅0019–0026 upgrade：新增知识/临时运行/journal表、旧表新增列与默认值，以及价格约束和等待唯一索引变更；没有执行知识发布/会籍写工具。事后只读检查为2条会籍、1条等待目标、0个新知识版本、0个harness-2工作区、0个operation_receipts。没有该默认库的此次迁移前快照，不能宣称已完成before/after内容一致性证明。当前状态备份保存在私有证据unintended-local-migration-after.dump，后续不擅自破坏性回滚。

新增scripts/migrate_agent_evaluation.py，显式限制本机journeyplus_eval_数据库，验证current_database，并设置env.py实际读取的环境变量再执行迁移。此事件意味着“默认库完全未迁移”的原声明已不再成立；G5数据保护结论不能沿用原声明。

- 冻结迁移在journeyplus_eval_migration_20260908从0023升级到0026成功；原49张表的计数和逐行hash全部与隔离源基线一致，见migration-verified.json。此证明仅适用于指定验收库，不覆盖上述默认库意外升级。

## 独立业务页面与补充验收

- published KnowledgePort 实体归属 knowledge/access.py；product/knowledge_public_api.py 和独立 knowledge_server.py 提供目录、活动、历史版简报、完整匹配图查询。共享消息ORM移至中立 workspace_models.py，旧导入兼容同一实体。
- 在拒绝任何 journeyplus.agent import 的新Python进程中启动独立知识服务成功；真实浏览器在8014完成22条路径的两页展开，以及Air Astana共享节点的3种申请方式详情，分别显示本步来源、USD49及同一历史版本简报链接。未构造模型或Agent工作区。
- 8013真实Agent资料卡的简报链接已复测：version_ref保持原值，活动简报展开、变化简报保持折叠。
- 新增历史/artifact游标绑定workspace、查询和结果快照；新消息/资料不会混入旧游标。大文本按可恢复章节/字符区间展开。显示分页保持模型选定对象顺序，不调用模型；跨workspace拒绝、revision冲突、渲染失败回送上下文有独立测试。
- S05补测3读并行→2写串行→后续读；旧owner过期不能结束run，换模型配置的恢复返回PARTIAL且不调用新模型。真实PostgreSQL两项事务/lease/回执测试复跑通过。

## 64次修复前行为基线（已完成，不是最终通过）

- 每个case-run复制独立数据库，模板 journeyplus_eval_formal_template_20260908 来自已核验0026隔离库。唯一显式fixture转换：在新模板中删除3条旧等待任务，给“创建等待”用例提供无active任务的初始条件；原隔离源和默认库未进行此转换。
- 两个manifest记录native、deepseek-v4-flash、temperature0.2、thinking=false、fixture hash及Python源码hash；代码快照baseline64-source.tar.gz，结果baseline64-development/与baseline64-holdout/保留。该批次运行旧进程中的冻结实现；后续修复不据此声称最终版本已通过。
- H02首次已观察到来源/目标反转及无工具依据宣称多条“已发布”酒店路径；A05首次把恢复SAS起点解析为汉莎→SAS，又把希尔顿起点解释为目标。结构检查为空不代表这些用例通过。
- H02同时暴露activity.read定位传入limit100、底层CatalogService最多50的实现错误，已改50并补无匹配名称detail回归。新增展示跨workspace API测试发现LookupError未映射HTTP码，已补404和无效引用422。
- 目前任务勾选表示对应实施项及其局部测试完成；G1/G2/G3/G4/G5门槛仍以整体验收为准，不能由勾选数量推导已经可切换。

## 上下文截断根因修复

A05修复前第一轮实际只有5条可见消息，但含工具调用/结果共14条内部消息。context.project错误地按内部message数量执行最近12条软窗口，因此下一轮“汉莎金呢”丢失整个先前对话。已改为按user和有正文的assistant可见消息计数，完整工具配对保留；新增8轮工具调用后仍保留上一用户请求的回归测试通过。不能将这部分失败全部归因于模型。

同时补齐大scalar/metadata的投影硬尺寸限制（完整原文通过artifact可继续读取），以及note的2000估算token限制。修复后A05原句仍出现外部经验方向混用/不完整结束，context-visible-fix保留；另以原模型thinking=true、temperature=0运行对照。更换模型须另获确认，因为runtime.md明确要求保持当前模型；已向用户询问是否允许现有接口提供的Pro模型进行对照，尚未据此替换模型。

真实浏览器再次刷新8013工作区，历史原文、Markdown表格、同一张实际活动卡均恢复且未重复；真实长回答中能显示“停止”按钮并提交取消。完整取消后状态仍在继续核验。

64次修复前基线已完成（110轮）：10个case-run有结构失败，另已人工确认A05首次、H02首次的硬性语义失败。结构通过上限54/64=84.375%，这不是语义通过率。case总耗时p50 14.59秒、p95 76.99秒、max106.29秒；单turn记录最大8次模型请求、10次工具、52673 input tokens、1497 output tokens，未发现记录超配置硬预算。详情baseline64-metrics.json；后续修复不能沿用为最终64次通过证据。

用户随后明确授权百炼平台任意可用LLM，已补runtime.md模型选型授权。使用现有模型清单中deepseek-v4-pro-0813和qwen3.8-max做A05/A12/P01/WAIT对照，不更改Workflow配置。

真实取消按钮发现完成/取消竞争后进度残留“正在停止…”：取消返回时若run已terminal，前端现在按实际状态结束并恢复快照；只有仍运行才显示等待停止。该场景原结果为完成，不能把它记成已验证成功取消。Agent共享图节点增加明确申请方式选择；详情与独立完整图复用纯函数，限制为选中版本、mapping及其实际费用，避免展示别的取得方式价格。

## 百炼模型对照、进一步修复与当前阻塞

- 用户已明确授权百炼/千问平台上的任意可用模型；不再需要逐模型确认。Agent 对照使用独立配置，未修改 Workflow 模型配置。
- 对照暴露 native schema 中 nullable object/union 使千问把对象参数生成为字符串。工具 schema 现展开对象属性与非空类型，仍保留 union 校验约束。修复后 qwen-instructions-fix 中 A12、P01、WAIT 的结构检查通过，实际保存、展示、等待回执均有记录；这只是核心场景局部通过。
- A05 的“全部路径”仍有语义失败，不能用结构检查为空代替验收。进一步修复投影预算追加 omission 元数据后溢出并丢弃整体数据的问题；仅压缩旧 turn，保留当前 turn 的工具结果，防止读取下一页后遗忘上一页。路线按实际字节预算分页，cursor 按实际返回条数前进，完整条件仍由 evidence_ref 展开。上述最新修复已有本地回归，但尚未完成真实模型复测。
- 评估器现在保存包括 instructions、前端及迁移文件的源码 hash 和源码归档，拒绝覆盖非空证据目录；启动失败也保存诊断。之前仅 Python hash 的旧记录保留，不能将其解释成最终代码证据。
- 百炼对 qwen3.8-max 和 deepseek-v4-pro-0813 的最小直接请求均返回 HTTP 400 / Arrearage，账户状态异常。已停止继续模型请求；这是外部服务阻塞，不记作模型语义验收结果。qwen-retained-pages 未完成启动，不能记作通过。
- 新增 ModelUnavailable 错误契约：仅保留 HTTP 状态和受限 provider_code，不记录原始响应/密钥；运行中明确结束为 PARTIAL，保留已生成内容，不进行格式修复重试或协议切换。前端保留该失败原因。模型、runtime、API 对应的 15 项局部测试通过。
- 最终版本需在百炼服务恢复后重新验证 A05 等核心场景，再冻结实现和新 holdout；原 8 个 holdout 已用于诊断，不再视为未见留出集。G2–G5 及 G6 均未完成，旧执行链尚未退役，automation/service.py 的旧 Agent 依赖仍待按切换门槛清理。

## 补充真实验收与隔离数据审计

- 在真实浏览器提交长回答并及时点击停止，确认回答停在第三部分，显示“此段回答中断，已保留”和“已停止。已经完成的操作保留。”，发送按钮恢复可用。此项是实际成功取消，区别于上述完成/取消竞争。
- 对修复前 64 个独立 case 数据库逐个核对 44 张非 Agent、非用户业务表的计数及内容 hash，差异为 0；表清单及逐库结果见私有证据 baseline64-db-audit.json。该审计不覆盖默认库意外迁移，也不代表最新代码的最终 G5 验收。
- 最新真实 PostgreSQL 事务、并发 lease、提交后回执恢复测试再次通过：2 passed。OpenSpec strict、git diff --check 和 workspace_v3.js / route_step.js 语法检查通过。
- 最新代码本地全量回归：801 passed、3 skipped、23 warnings，耗时 77.24 秒；记录 regression-final-local.txt。跳过项仍保留为跳过，不能视为通过；其中两个 opt-in PostgreSQL 项已在上述显式隔离库单独通过。警告为测试客户端及 SQLite datetime adapter 弃用提示。全量本地通过不替代真实模型和浏览器 G5 门槛。

## 充值后上下文成本审计（2026-09-08）

用户充值后真实 API 已恢复；用户允许开发验收不设总费用限制，但要求避免 Max 等高价模型，并进一步明确不能接受普通 Agent 单次请求上下文过重。当前暂停新增真实模型调用，先处理上下文效率。

审计 flash38-restored-core、flash38-thinking-core、flash38-dialogue-fix、flash38-atomic-budget、flash38-history 五组 qwen3.8-flash 记录：129 次带 usage 的请求，共 1,384,566 input tokens、27,471 output tokens。单请求输入最小 4,883、中位 10,163、p95 17,920、最大 19,829；单用户 turn 累计输入中位 42,901、最大 82,851。cached input 922,624 包含在 input 总数中，不能重复相加，也不能据此断言平台免费额度或账单扣减规则。统计不含启动探测及无 usage 的失败请求，不能当成账户完整用量。原始汇总：私有证据 qwen38-context-audit.json。

结论：测试频次与上下文重复均有贡献，不能只归因于测试多。工具 schema JSON 约 18.8 KB，instructions 约 3.9 KB；这是字节数，不是 token 数。当前每次模型请求重复携带工具定义，当前 turn 的多个工具结果可各保留至 12 KB，后续请求再次携带累积结果；最近对话按完整 turn 保留，工具正文占用对话预算。现有历史窗口/原子投影正确性修复不等于效率已达标。后续应先离线对比上下文组成和压缩效果，再以少量代表场景验证实际 usage 与答案正确性；提高预算不能作为效率修复。此前全量回归记录对应此前代码，不覆盖充值后所有新增修改；最终 G2–G6 仍未完成。

## 回答正确性与上下文效率专项（进行中）

- 历史已完成工具配对整体投影为明确标注的引用索引，保留用户原话、最终回答、状态及原始查询/回执元数据；不调用额外摘要模型。本轮分页数据、未完成批次及无完整结果引用的配对保留。纯传输空字段不再重复发送，领域内 null/false/未知状态不删除。
- 精简 instructions 和工具描述；路线概览减少重复端点/证据引用/统计，inspect 对共享步骤只返回一次。原始路线及版本仍保存在完整 artifact。
- 新增离线回放 scripts/audit_agent_context.py。同一组45个模型消息边界回放，输入JSON字节总量1,651,328→1,228,545（下降25.6%），中位30,719→22,862；这不是provider token对照，且不包含后来提示词细调。模型适配器新增真实请求input_bytes/schema_bytes/tool_result_bytes记录，真实token继续使用provider usage。
- 物料按完整原始section匹配名称后再分页，修复先切小块再匹配时丢失同条规则后续费用/条件的问题，并避免原始options与sections副本重复展开。
- 名称绑定增加唯一完整英文词组匹配；多个项目匹配仍报歧义，不进行词片段匹配或猜等级，未写入名称库。回归覆盖唯一词组、共享词组、Sam不能绑定Sample。
- **纠正之前对重复路径的解释**：A05两页中出现同名路径，并不能证明它们是不同规则。已通过实际ROUTES artifact定位关键根因：第一页按内存routes字典插入顺序分页，续页读取PostgreSQL JSONB时键顺序改变，因此重复/遗漏。现保存显式route_order列表；旧无列表快照采用稳定排序。真实PostgreSQL往返测试确认25条结果顺序一致、无重复无遗漏。独立同名规则变体元数据仍可表达真实变体，但不用于掩盖分页错误。
- efficient-flash38-core 失败保留：来源/目标反转、无依据联盟解释、缺展示回执。efficient-plus37-core 为诊断失败：部分条件理解改善，P01有真实展示，但A05受上述分页错误影响；期间artifact_views曾修改，不能视为最终冻结代码验收。
- correct-order-plus37-core/A05-1 已实际完整展示11条路径；但最后Hilton来源被错误限定到上轮结果的Gold目标等级，仍判失败。第二次A05主动中断，记为CANCELED，不计通过；随后停止评估进程，未完成批次不能视为正式验收。评估器补充上层取消检测，防止runtime处理单run取消后继续发起下一验收case。
- 分页修复后的全量本地回归814 passed、4 skipped、23 warnings（67.04秒）；4个跳过项含3项opt-in PostgreSQL，它们在显式隔离库另跑3 passed。后来查询条件提示细调后的37项针对性测试及OpenSpec strict通过。原始记录 regression-correct-order.txt。没有Git提交、生产切换或默认库迁移。


### 专项后续证据（仍未通过最终语义验收）

- native 工具名改为可移植的 ASCII 名称，历史请求使用同一映射，响应精确恢复内部名称；不接受截断名称的猜测。真实 Kimi 对照定位此前 evaluate/UNKNOWN_TOOL 为适配器问题；修复后全部5轮工具可执行，但仍发生擅自限定目标等级、最后丢失目标项目及补充无依据联盟说明，因此不通过。
- 旧结果索引增加原始对象名称、路径和引用，支持后续直接 inspect，减少为找引用逐页读取旧全文。部分费用明确返回 known_subtotal 与 UNKNOWN 总价，避免将已知0误报免费。完整原始数据仍可取回。
- 最新离线同45个消息边界的输入 JSON 总字节 1,349,016，中位25,376，最大48,744；基线1,651,328。此版包含对象索引，数据比早期仅保留结果引用的版本多，但可减少重新读取；不能直接把字节下降当成实际token或成功任务成本下降。
- 最新全量回归817 passed、4 skipped、23 warnings，66.72秒，见 regression-portable-model.txt。此前显式隔离 PostgreSQL 三项通过。单元测试通过不能替代真实回答正确性。
- DeepSeek Flash、Qwen 27B、Coder Next、Kimi 的失败记录均保留；GLM 启动被平台以产品未激活拒绝，没有执行激活操作。尚未确定通过验收的最终经济模型，任务清单及切换门槛不勾选。


- 追加定位历史压缩的查询快照覆盖错误：同一轮 search 后 inspect 无 effective_query，旧实现直接覆盖 last_metadata_per_tool 导致检索范围消失。现保留最近实际返回的完整查询；新查询整体替换，显式空目标不会被旧目标补回。补充回归覆盖 search→search重置→inspect→下一轮，并回放真实失败记录确认目标恢复。
- 查询快照修复后55项针对性测试通过，全量 pytest 退出0（regression-query-snapshot.txt），OpenSpec strict通过。随后仅提示词证据边界有调整，需以新真实记录验收。
- preserved-query-plus37 全5轮结构通过、最后Hilton→Royal Jordanian不限等级查询正确，但仍输出无证据联盟原因/替代建议，以及“Gold Sparrow非完整金卡”，判语义失败。不能据此宣称回答正确性已经解决。


## 无业务模型的输入视角审查

用户要求先由开发助手替代业务模型审查，再在最后进行真实模型验收。审查与证据索引见[review.md](review.md)。本阶段实际业务模型API调用为0，所有手动工具执行使用独立journeyplus_eval_review_20260908。原有真实失败记录不删除，人工完成不计入模型通过率。撤回有损历史压缩，修复nullable工具Schema、身份候选绑定、活动完整分页、详情容量、祖先字段、等待冲突及费用/资格表述。最新全量822 passed、4 skipped，后续费用范围和版本字段34项针对性通过。最终模型/浏览器验收仍待执行。

## 2026-09-08 人工模型位置审查续验

完整发现/修复对照见review.md。没有业务模型API调用。manual-review-page-fixed在默认45k/60k输入预算下完成11条路线的7+4分页、真实展示回执与回答；manual-review-scope-fixed的三分页预算失败和人工超时仍保留，不覆盖。manual-review-history用固定前缀制造历史窗口，再由人工读取真实输入、找回原始筛选并仅修改free_only，两个查询保留allow_challenge=false。

网络真实发现Courtyard Marriott（不在旧REVIEWED三项目内），读取StatusMatcher报告137555、独立解析并refresh；两次读取OK、refresh非缓存且observed_at变化，可比性UNKNOWN。网络测试不依赖正式路径、不调用LLM。network-review-discovery.json和network-review-report.json保留实际来源和文本。

隔离浏览器8023预览使用显式NoModel适配器、关闭维护，不能请求业务LLM。真实展开8→11路线、打开皇家约旦步骤条件并产生focus，直接访问绑定版本简报、展开历史11:53:12版本，页面显示历史标记和旧版内容。in-app浏览器中target=_blank点击未出现新标签，因此简报目标通过观测到的完整链接另开标签验证，不把它记作弹窗交互通过。费用PARTIAL标签及相同URL简报去重复验通过；初次复验发现静态资源缓存，增加版本参数后确认新UI生效。

全套Python回归regression-review-final.txt：824通过、4跳过、23 warnings，exit 0（双quiet未打印汇总，按进度统计）；其后仅有静态资源版本参数和新增PG恢复测试。JavaScript图结构3项通过。真实Postgres postgres-review-resume.txt：4通过（2.95秒），包括提交成功、工具结果尚未记录时的故障窗口恢复，复用同一operation_ref、会籍/receipt各一条，旧owner无法执行。该故障为显式模拟窗口，非真实kill进程。

20张正式知识及来源表与隔离模板逐行规范化hash比较一致，different_tables=[]，证据review-knowledge-template-comparison.json。这证明本轮隔离review库相对模板未改变这些表；不代表默认业务库的历史迁移问题已经消失，也不替代部署前后审计。

OpenSpec strict和git diff --check通过。尚未执行冻结后真实模型64组验收、G6退役旧控制链和本地切换；不把人工或确定性通过冒充这些门槛。

### A05首次最终阶段失败（随后返回人工修复）

final-a05-flash-r1：五轮COMPLETED但人工语义FAIL，17业务请求、180991 input tokens，不含probe。漏读分页、错误扩大皇家约旦范围、最后多余澄清及无依据联盟解释，详见独立semantic-review.json；原case文件未改写。未扩大批次，也未换模型。复算确认第三轮仍有初始SAS金卡用户消息，撤回“该消息被挤掉导致本次失败”的推断。

返回人工后实现普通/收尾估算区分与收尾无tools schema、web.read同快照正文/链接分页、可展开表单控件索引，并恢复候选端点。manual-review-web-controls正文4532字符（此前10822），保留两组报告摘要；五个控件的索引显示来源和目标各152选项，不再将选项混入正文。该人工run有一次45秒人工等待重试，最终COMPLETED，不能计性能；正文已读完而余下6链接未展开，回答明确此范围。

新增网络分页测试曾在单独运行时因SQLite fixture创建前未注册Artifact元数据而失败，已改为测试收集阶段注册；与真实Postgres表结构无关。之后model/network/runtime共27项通过；后续全量记录为regression-web-budget-review.txt。

### 2026-09-08：A05 第二轮未通过，继续人工工具契约审查

证据：`final-a05-flash-r2/A05-1.json`、`semantic-review.json`，FAIL；22 请求、246394 input tokens、69.7 秒。全量路径读取/展示改善不能抵消末轮目标等级污染和无充分证据结论。上一轮全回归 `regression-web-budget-review.txt` 为 828 passed、5 skipped、23 warnings；之后增加原查询 lineage 和网页覆盖契约，针对性 42 项通过，需再次全回归。人工真实隔离库证据 `manual-review-query-lineage-r2`：两轮完成，未调用模型 API。G5/G6 仍未通过。

### 无 LLM 浏览器传输验收与最新全回归

`regression-lineage-review.txt`：829 passed、5 skipped、23 warnings，102.23 秒。`browser-transport-review/` 保存人工 ModelPort 输入及取消后完整工作区。独立 8024 端口、隔离 review 库、网络关闭、无维护任务/Workflow/模型客户端；浏览器真实发送后看到两个独立 assistant 正文（工具阶段、最终阶段），再发长响应、刷新后原文与后续 SSE 接续，点击停止恢复发送按钮并保留原文；数据库确认第一 run COMPLETED、第二 CANCELED、末段 metadata.interrupted=true、无重复用户消息。ModelPort 是预先编写的人工回答，只证明传输/前端，不冒充真实模型语义验收。完成任务 8.2，P04 的真实模型部分仍在 G4/G5 中核验。

### 配置隔离、旧会话浏览器导入与容器参数适配

新增 Workflow/Agent 双向依赖和配置检查，与原 provider/独立知识页共 14 项通过。`isolation-review-final.json`：review 库和两次 thinking-r2 case 库的 20 张知识/来源表均与干净模板相同。`browser-import-review`：真实点击导入合成旧会话，两条原文保留，旧 pending_action 未执行，用户会籍数量不变、无 run、未导入旧执行 flags。测试预览 8024 已停止，未操作真实旧用户会话。

`final-a05-flash-thinking-r2` 两次均 FAIL，显式 tool_choice=none 后仍有供应商返回调用的事实；简单 echo 探针不保证复杂轨迹遵循，不能宣称已解决。`final-a05-qwen38-r1` FAIL：嵌套 query/program 被原生接口返回为 JSON 字符串，所有路线调用均被严格 DTO 拒绝。

适配层新增 schema-guided container decoding：只有 schema 不允许 string 而允许 object/array 时解析合法 JSON 容器，保留全部值、null 和未知字段，之后仍走原严格校验；string 合法时不改写，不推导身份或参数。Native/JSON 两种协议均有测试，metrics 记录 wire_decodings 字段路径，不输出敏感值。40 项协议/核心检查通过。`manual-review-wire-decoding` 人工位复现原 native stringified query，在真实隔离 PostgreSQL 成功执行 SAS Gold→国泰、不限目标等级检索；返回 0 候选及知识缺口，人工结论保留范围，COMPLETED。全回归正在重跑。

容器参数适配后全量回归：`regression-wire-decoding.txt` 为 835 passed、5 skipped、23 warnings，92.04 秒。其后仅在单一 instructions 中澄清常见名称/俗称可由模型理解并明确假设检索，不要求用户复述标准名称；不新增品牌对照表。固定 24 development+8 holdout fixture 的 SHA256 与 baseline64 及本轮各次 manifest 一致，未修改测试话术或样本。8.5、9.1 已按对应隔离/冻结证据完成；真实 G5 尚未通过。


## 用户审核前系统收口（2026-09-08，本轮最新状态）

本轮遵循 charter.md，全程未调用第三方模型 API。系统改造、人工逐次 ModelPort、真实隔离 PostgreSQL/公开网页/浏览器验收以及旧链退出见 [系统侧审核包](system-review.md) 与 [人工证据索引](manual-evidence.md)。本节更新当前阶段状态，不撤销上文历史失败或默认本机库意外升级披露。真实模型 64 case-run、实际 token/延迟及最终语义硬门槛仍待用户审核明确批准后执行。
