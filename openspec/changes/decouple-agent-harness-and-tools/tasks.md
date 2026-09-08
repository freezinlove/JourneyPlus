> 当前实施顺序与授权边界以 [实施总纲](charter.md) 为准：先完成系统侧人工双视角验收与本地架构收口，交用户审核；审核明确允许后才调用第三方模型 API（含探针）。原真实模型验收项保留待执行。

> 2026-09-08 独立复核：以下保留既有实施勾选记录，但不再代表系统侧全部验收通过。新发现、受影响任务和修复顺序见 [独立审计](independent-audit.md)；11.6 的就绪结论暂不成立。此次为审计，未将新问题标为已修复。

## 1. 基线和架构边界（G0）

- [x] 1.1 按 design 阅读顺序审阅全部附件，记录当前git工作区、迁移head和旧API调用方；不修改历史change完成状态。
- [x] 1.2 创建harness/adapters/tools/services及composition职责骨架，添加S01/S02依赖边界测试，不移动整个WorkspaceService冒充拆分。
- [x] 1.3 按runtime/tools定义公共DTO、12项工具schema及ports，验证未知字段、作用域和错误契约。
- [x] 1.4 建立隔离数据库和验收manifest；记录正式知识/用户数据before基线，确认Workflow不需启动。

## 2. Agent模型适配和通用循环（G1）

- [x] 2.1 实现独立AgentModelPort、NativeTools流式参数及call_id配对；保留Workflow AIProvider行为和参数。
- [x] 2.2 实现JsonActions兼容、启动能力探针及固定run协议选择，真实验证现有模型echo往返并记录限制。
- [x] 2.3 实现无业务枚举的runtime loop，允许直接回答、工具结果后继续、追问和结束；编写S03/S04/S06测试。
- [x] 2.4 实现注册器、参数校验、结构化错误回送、独立读并行/写串行及操作级effect元数据。
- [x] 2.5 实现软硬预算、真实usage、连续格式错误和重复无进展反馈；验证超过三次请求仍可完成任务。
- [ ] 2.6 编写单一instructions.md，禁止固定工具使用顺序、目录必经和品牌话术；完成G1验收。

## 3. 持久运行和上下文（G2基础）

- [x] 3.1 创建storage-context定义的四张additive表及索引/外键，复用现有message/turn/delivery，验证Postgres升级和旧数据读取。
- [x] 3.2 实现harness-2会话、通用parts消息、artifact类型引用与workspace作用域校验。
- [x] 3.3 实现checkpoint/lease/heartbeat、工具intent及结果日志；网络和模型调用不得持数据库事务。
- [x] 3.4 实现24小时临时清理与持久operation_receipts分离，验证级联及回执保留。
- [x] 3.5 实现上下文投影、完整历史索引、工具配对保护、workspace.read/note；验证A15/T03。
- [x] 3.6 实现取消、SSE断线续订及崩溃恢复，执行R01/R02/R03及尚未完成参数不得执行测试。

## 4. 独立知识和路线工具（G2）

- [x] 4.1 实现只读知识port、catalog.lookup和activity.read；支持直接detail/evidence与版本/覆盖/可展开引用。
- [x] 4.2 实现IdentityInput绑定：名称和ref、别名作用域、候选歧义、CATALOG_GAP；不能要求先有catalog回执。
- [x] 4.3 实现RouteRequest sources模式及完整输入、query_ref+patch、cursor绑定，无隐式last_query和旧scope状态。
- [x] 4.4 适配RouteService search/inspect/compare，显式actual sources/target/constraints及费用资格未知，保存结果artifact。
- [x] 4.5 提取推荐/最小成本/经验可比等纯计算指标，移除原话解析和最终选择覆盖；评分说明只作为数据。
- [ ] 4.6 用真实模型和隔离知识完成A01/A02/A04/A05/A07/A08及T01/T02/T03，记录G2结论和首次失败。

## 5. 用户会籍和等待任务（G3）

- [x] 5.1 实现holdings.read及快照，未解析会籍不从结果中静默丢弃。
- [x] 5.2 实现holdings.write授权原话引用和明确create/update/delete，取消普遍二次确认，不用关键词替模型判意图。
- [x] 5.3 实现未解析原始会籍保存、自然键NOOP、不同等级create冲突和expected_revision更新。
- [x] 5.4 实现用户变更、journal、operation_receipts原子事务；验证重复key/不同payload、崩溃窗口及恢复。
- [x] 5.5 实现waiting.manage及单active冲突，复用独立确定性检查，不依赖旧Controller或Workflow发布。
- [ ] 5.6 实测A11/A12/A13/A14、W01–W04；验证无授权零写入和已提交取消回执，完成G3。

## 6. 自主联网与经验能力（G4部分）

- [x] 6.1 实现web.read独立公开HTTPS读取、缓存/refresh、链接提取、redirect/DNS及资源边界，保留页面artifact。
- [x] 6.2 实现StatusMatcherBuiltinSearch，真实主页company链接发现和有界报告列表；不以REVIEWED三项目为能力边界。
- [x] 6.3 实现可配置HTTP JSON SearchPort及未配置UNAVAILABLE；不得采购或虚构通用搜索能力。
- [x] 6.4 解耦report解析与OptionMapping，实现research.parse原始身份、时间与可比性；无正式路线仍可调查。
- [x] 6.5 移除research关键词门、refresh覆盖和自动官方recheck；模型通过工具自主追加核查。
- [ ] 6.6 完成真实N01/N02/N03和A09/A10/A16，记录新项目真实读取及外站失败边界。

## 7. 模型拥有展示与自然回答（G4完成）

- [x] 7.1 将_assemble拆成无用户原话依赖的纯渲染服务，保留版本/边/价格一致性校验。
- [x] 7.2 实现display.present、模型对象顺序/角色/比较列、实际回执及可选下一步建议。
- [x] 7.3 接入模型直接正文与多message流，移除无条件verified_route_text覆盖、数字白名单删句及固定narration请求。
- [x] 7.4 实现单入口卡片/节点详情、历史版简报链接和focus对象反馈，保持无模型分页。
- [ ] 7.5 验证P01–P04、卡图顺序=模型选择=回执，以及渲染错误回送而非静默替代，完成G4。

## 8. API、前端和业务隔离

- [x] 8.1 实现v3 agent_api薄路由、composition和独立配置，Workflow参数/路由不变。
- [x] 8.2 适配workspace前端run/SSE多message、取消/恢复/回执；普通知识与完整图/简报页面保持独立。
- [x] 8.3 实现旧workspace只读及显式导入：原文、legacy展示映射，禁止导入语义flags或执行pending_action。
- [x] 8.4 实现运行中第二消息/焦点冲突、幂等POST和API错误码；浏览器输入不因409丢失。
- [x] 8.5 执行I01–I04和旧页面只读对比，确认Agent操作没有正式知识写入、没有启动Workflow。

## 9. 真实整体验收（G5）

- [x] 9.1 冻结24个已知会话与8个holdout会话及数据snapshot，覆盖acceptance所有语义类别；禁止根据测试话术硬编码。
- [x] 9.2 运行确定性全套、Postgres事务/并发/恢复及native/json协议契约测试，保存各类真实结果。
- [ ] 9.3 运行64个真实case-run并逐轮核对actual inputs、结果、版本、写入回执、UI展示；保留首次失败。
- [ ] 9.4 统计完成率、不必要澄清、无效调用、首字/总耗时和tokens；按硬门槛与目标分别报告，不能静默跳过不支持的流式。
- [x] 9.5 更新本change verification.md（实施时新增）、证据索引和已知限制；未达硬门槛不得进入切换。

## 10. 本地切换、退出旧控制链（G6）

- [x] 10.1 切换本地预览为harness并真实浏览器验收原SAS/汉莎/国泰对话、全日空场景、会籍保存和简报点击；不切生产。
- [x] 10.2 退役v1/v2 Agent写入口为410/新版入口，保留旧会话只读和非Agent业务路由。
- [x] 10.3 清理旧语义路由/PLAN-RESOLVE/自动推荐/narration执行链及永久legacy开关，检查所有生产调用方无旧控制器依赖。
- [x] 10.4 演练服务回退但保留新表/用户操作/journal，确认不自动downgrade、不撤销已成功写入。
- [x] 10.5 OpenSpec strict、链接/依赖检查和最终回归通过；报告未提交文件、验证结果与部署边界，不自动Git提交或归档。

## 11. 用户审核前系统收口（本阶段主清单）

- [x] 11.1 落地独立总纲，明确双视角人工验收、正确性优先及第三方模型审核门。
- [x] 11.2 全面审查六项规格、附件、数据库结构、依赖和调用方，建立系统侧逐项证据矩阵。
- [x] 11.3 人工坐在模型接口逐步验收全部工具及会籍/等待任务生命周期，核对数据库 before/after。
- [x] 11.4 完成人工多轮、历史/笔记、渐进披露、上下文预算、错误/取消/恢复和展示焦点验收，修复发现的问题。
- [x] 11.5 前移完成本地旧入口退役、控制链清理及独立启动验证，保留只读历史和非 Agent 页面。
- [x] 11.6 完成回归与最终证据审查，提交接入真实模型前审核包，等待用户明确批准后才执行第三方模型验收。

## 当前阶段交付说明

系统侧审核包见 [system-review.md](system-review.md)，逐项人工证据见 [manual-evidence.md](manual-evidence.md)。第 11 节按用户新顺序完成；第 10 节指本地无第三方模型的代码切换、UI 回放和服务配置回退，未部署生产或执行 downgrade。

2.6 的单一指令已实现并人工使用；4.6、5.6、6.6、7.5 对应的系统侧能力、人工及确定性/数据库/公开网络/UI 检查已完成。因为这些原任务还包含完整 G1–G4 或真实模型语义门槛，保留未勾选，待用户批准模型验收后收口。9.3/9.4 保持待执行，旧失败基线不充当最终 64 case-run。

最终全回归 626 passed / 5 skipped；4 项真实 PostgreSQL harness 测试另行通过，剩余 1 项 PostgreSQL 已发布事实不可变触发器检查亦另行通过。详见审核包验证记录。
