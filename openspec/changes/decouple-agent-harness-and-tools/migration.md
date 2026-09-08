> 当前实施顺序与授权边界以 [实施总纲](charter.md) 为准：先完成系统侧人工双视角验收与本地架构收口，交用户审核；审核明确允许后才调用第三方模型 API（含探针）。原真实模型验收项保留待执行。

# 实施映射、迁移和退出旧控制链

## 1. 源码迁移表

| 当前文件/能力 | 目标处理 | 禁止带入的行为 |
|---|---|---|
| agent/workspace.py message/_tool | harness/runtime + tools handlers + persistence ports | 当前问题关键词路由、隐藏查询、三次上限、阶段锁定 |
| workspace._assemble/_verified_answer | services/presentations + tools/presentation | 覆盖正文、自动推荐和下一步建议 |
| task_context.py / completion.py / turn_planning.py | v3不导入；旧对话导入只取原文，不迁移逻辑 | scope flags、强制身份读取、未执行某工具不允许回答 |
| display_focus.py | UI明确对象直接写focus元数据 | 按“这个/条件”正则自动INSPECT |
| research_intent.py / research_recheck.py | 刷新/调查由模型参数决定，recheck成为activity.read的普通使用 | 关键词授权、后台自动追加官方核查 |
| recommendation.py / research_ordering.py | 评分和可比指标可在routes compare结果中输出；不执行最终排序覆盖 | 必须少步骤优先、自动一主两备 |
| adjustments.py | 保留纯最小成本计算并通过routes compare明确调用 | 解析原话改预算、自动stage proposal、截短问题 |
| knowledge/reads、packets、routes | 包装只读port；拆除读取完整Agent state的适配代码 | 以未给参数代表模型想用存量/旧目标 |
| step_research/report_pages/step_observations/research_http | 拆为独立web read+parse服务；保留解析、日期、限制和网络保护 | 强制OptionMapping存在和三项目硬门槛 |
| delivery.py、workspace_models.py | 提取通用持久event/run能力，兼容旧表 | 固定110秒代替通用heartbeat和deadline |
| workspace确认/StatusHolding journal | UserMemoryPort原子操作与回执 | 所有明确写入仍必须PROPOSE再确认 |
| WorkspaceWaitService/waiting.py | 统一等待数据端口，沿用确定性后台查询 | 唤醒时重走旧AgentController流程 |
| product/knowledge_api.py | 非Agent知识路由保留；Agent路由逐步转agent_api适配 | 因切Agent改变简报/完整图API |
| product/api.py v1 AgentController | 验证期保留旧入口，最终退役写入口 | 永久维护两个语义控制器 |
| product/static/workspace.js | v3事件、回执、取消和焦点 | 根据文本关键词决定发哪个业务请求 |

不修改业务模块仅因文件名带agent；先查看调用方，纯算法可复用。最终删除旧模块前rg确认没有生产入口引用；历史测试改为迁移/只读兼容测试。不能单纯为了测试通过保留不可达但继续被导入的规则。

## 2. 配置与装配

- `AGENT_RUNTIME=legacy|harness`默认legacy直到G6真实验收；v3隔离入口显式harness；新runtime构造不接受legacy max_calls。
- `AGENT_PROTOCOL=auto|native|json`及runtime.md预算设置；Workflow配置不改。
- `AGENT_NETWORK_ENABLED`独立于Workflow采集开关；预览沿用用户已经授权的公开研究，正式值不自动开启。
- `AGENT_SEARCH_BACKEND=statusmatcher_builtin|http_json`；内置可用于scope=statusmatcher，可选通用搜索配置按tools。
- `AGENT_READ_DATABASE_URL`与用户写入factory逻辑分开，可指同一库不同session权限；日志不得输出URL/secret。
- composition创建实际模型client、12个注册项、ports；provider替换不改工具，新增工具只改注册/handler/schema/test，不修改runtime if/elif。

不得把新版harness直接塞回WorkspaceService的一个if分支后继续读取旧state。API兼容只转换输入输出，不生成PLAN/ASK等旧控制动作。

## 3. 分阶段门槛

G0 文档/契约：规格与旧要求替代闭环；提供tools schema和dependency tests。
G1 模型/harness：echo工具真实调用、native/json协议测试、自然直答、失败后回送、预算及取消；不接用户写入。
G2 只读：在隔离库使用activity/catalog/routes/workspace，真实查询及无命中范围正确；所有脚本只能由工具handler显式调用。
G3 用户记忆：授权原话、未解析保存、更新冲突、并发/崩溃/重放测试；用户写入journal一致。
G4 网络/展示：真实StatusMatcher发现与报告，无路径也可调查；模型顺序=回执=UI；链接只读简报。
G5 完整评测：见acceptance；常识直答、未见话术、多轮切换、联网、写入、流式及隔离验收。失败不得用新增语义正则修复。
G6 本地切换与清理：预览切harness，验证当前端口真实请求、旧会话导入及读页面不变；退役旧写入口，清理旧控制代码，保留迁移文档。

每阶段只在自己的验收通过后推进，失败保留原记录并修能力/协议/工具说明，不靠更换测试话术掩盖。用户已授权按计划实施不等于授权Git提交或生产发布。

## 4. 旧 API 和历史会话

验证阶段v1/v2写端点仍走legacy仅服务旧会话，v3走harness。G6后 `/workspace`只创建harness-2；v1/agent/turn 与v2 messages/deliveries/confirm旧写入口返回410 `AGENT_RUNTIME_RETIRED` 和新工作区入口，不解析为旧动作。v1/v2知识读取、原完整图/简报不退役。

GET旧workspace允许只读历史。用户点击“在新版继续”才POST v3 import：复制用户/assistant原文，标legacy来源；旧图卡以只读IMPORT artifact持有原snapshot/payload，并保存原对象→新ref映射供查看。旧pending_action不执行，作为历史待处理信息告知模型；不迁移旧flags、lease、run或隐藏自动查询状态。若旧记录已过期返回410，不伪造历史。

新旧读入口可共享存储但不共享decision engine。最终不保留legacy运行开关作为永久分支；回滚通过上一版本进程和端口切换，harness-2对话在旧版保持只读/不支持，不能硬转旧schema继续执行。

## 5. 数据迁移与回滚

只新增runtime表及必要索引，不重建正式知识或删旧消息。迁移升级前记录当前head及表计数，拷贝隔离库，运行Alembic upgrade、用户journal一致性检查与旧知识读取对比。不得执行旧文章回填或Workflow采集来“修好”Agent。

原测试库可用于验收，正式数据库不自动写入。会籍写入验收使用明确测试用户数据/隔离库，保存before/after和操作回执，不能把测试会籍塞入用户真实账户。

回滚先停止接收新runs，取消或等待正在执行的工具并记录receipt，恢复旧进程路由；新表和journal不删除、不自动downgrade。已成功用户写入是业务事实，不因代码回退撤销；旧读取已兼容现有StatusHolding fields。确认用户数据可读取后才允许任何后续清理，生产另行授权。
