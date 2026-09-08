# 讨论决策、旧要求替代与不变边界

## 1. 本次用户明确要求的追踪

| 用户要求 | 落点 | 验收 |
|---|---|---|
| 模型利用自身常识理解全日空，不必须证明标准名 | design D1/D3；tools IdentityInput | A01/A04 |
| 名称对照表只是可读可不读的工具 | T1、T2/T3支持name输入 | A02/A04 |
| 模型决定识别、持久化、查询、是否知道和是否调查 | runtime单loop；T4/T5/T8/T9 | A03/A09/A12 |
| 程序能力解耦，而非义体式绑定 | D2依赖规则，migration映射 | S01/S02 |
| harness清晰、模型独立性强、脚本干净 | runtime ports、统一协议、清理旧控制器 | S01/G6 |
| Agent与已有Workflow两个板块互不干扰 | D5只读知识port，API隔离 | I01/I02/I03 |
| 可以展开原简报，但业务链路分开 | presentation版次链接 | P03/I02 |
| 后续AI可直接实施，核心设计本次落盘 | 12工具、表/协议、错误/迁移、tasks | 文档闭环检查 |

只记录本轮上下文中实际出现并明确接受的讨论；不声称恢复了更早完整聊天记录。前次运行样本是回归输入，不是本次harness通过证据。

## 2. 冲突要求逐项替代

| 历史来源（保留原文件） | 被替代要求/实现 | 新要求 |
|---|---|---|
| improve-agent-conversation-and-live-research/design.md 省略句最终设计 | RouteTurnPlan→RouteIdentitySelection→程序执行→第三次narration | 自主工具loop；不强制阶段或先查目录 |
| 同change task_context及完成条件 | 正则/标记保持或清空条件，未查路线阻止ANSWER | 模型提交完整查询/显式patch，结果反馈模型 |
| 同change CATALOG/等级保护 | 保存/查询前必须先披露目录引用 | 业务工具接受名称，目录独立可选，执行关联仍准确 |
| 同change 三次调用/流式改写 | 包括修复最多3次，程序简报为正文唯一来源 | 可配置通用预算；模型直接正文；协议兼容限制如实说明 |
| rebuild-membership-knowledge-and-agent/agent-runtime-design.md 及 conversational-membership-agent | 旧动作枚举、强制proposal与确认门、服务端完成判断 | 通用tools消息；授权单项写入直接执行；操作回执可靠 |
| 同change agent-result-presentation 与 presentation-research-design | 服务器推荐顺序/自动结论文案 | 模型选择，渲染器忠实展示；算法只提供指标 |
| 同change scoped-statusmatcher-research | 仅用户特定研究话术、必须步骤身份、固定已登记公司映射 | 模型选搜索/读取/解析，可先无正式路线研究 |
| implement-membership-strategy-agent 的旧Controller设计 | 解释→目标→策略固定链，旧v1入口 | 仅迁移历史，新请求统一harness |

旧change打勾只表示按当时方案实施，不代表新需求已经实现；不修改历史tasks以虚构本次完成。新tasks全部未勾选。

## 3. 明确保留

保持已发布知识版本、来源证据、未知与覆盖说明、真实路线算法与费用计算、用户数据journal、UI单主入口、分页/版本引用、用户假设不自动变持有会籍、24小时临时工作区、等待任务独立业务数据。保留“完整图与简报供Agent打开”的产品联动，不共享Workflow控制链。

不再要求模型只会选ID，也不允许模型编造已执行的读取或写入。常识可直接回答；实时费用和当前资格结论仍应使用合适数据，模型可以说明尚未核实，而不是所有输入都必须查数据库。

## 4. 本次不做

Workflow采集/提取/发布重写、正式知识全量回填、全球所有品牌实体建设、新增长期用户画像、多Agent团队、自动申请/付费、生产发布、Git提交。不以工具化名义把任意shell或SQL开放给模型。后续实施只在本change边界内，不因目录缺失绕路重做AI Workflow。
