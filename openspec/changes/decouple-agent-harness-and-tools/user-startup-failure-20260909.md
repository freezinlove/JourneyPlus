# 用户正常服务测试失败（2026-09-09）

用户输入“你好”后输入“我有万豪白金，我想要所有匹配的可能”，页面没有任何业务回答，仅显示 PARTIAL。这是未完成正常部署验收就交付给用户的系统缺陷，不能归因于模型能力。

## 原始证据

运行 af3fefca-e260-48c5-adc0-144b09385109，正常库 journeyplus。原消息、工具参数、结果、事件和预算已只读导出到 `.secrets/user-failure-20260909/original.json`，未修改用户失败对话。

- 正常库 membership_programs、membership_tiers、activity_knowledge_versions 均为 0；旧 fact_sets 66、briefs 68、article_briefs 23、article_opportunities 23 等资料存在。结构迁移不等于新版知识迁移/发布。
- 模型已经用英文 Marriott Bonvoy 和 Platinum 查目录，仍为空；这不是单纯中文别名问题。
- 5 次模型请求、6 次工具调用、39948 输入 token、630 输出 token。最后的 partial 信封包含 minimum_objects=0、未定义的 delivery.status 和错误调用 ID，校验拒绝。runtime 因 finalizing 立即终止，没有使用仍可用预算修复；UI 又覆盖具体错误为泛化提示。

## 本轮修复

- 知识端口提供目录/等级/已发布版本计数及就绪状态；状态 API 明确 ready_for_route_queries=false，UI 加载时提示未接入知识，模型上下文也披露。
- 空目录与空查询结果分开；目录/路线工具返回 KNOWLEDGE_NOT_READY，不再说请求的身份未收录。
- finalizing 只禁止新工具，不禁止硬预算内的正文格式修复；错误反馈包含具体字段；连续拒绝返回明确终态说明。
- 禁止把原始 PAGE 或 web.read 的 MATERIAL 整页文本直接当业务事实渲染。
- 不改正常知识数据，不复制测试数据库到正常库，不调用 Workflow 填数据来掩盖问题。正常库缺少新版知识的迁移仍未完成。

## 真实复跑与限制

在 journeyplus_eval_user_failure_0909（正常失败库的隔离副本）以 qwen3.8-flash 跑相同两句。问候 COMPLETED，第二句仍 PARTIAL：正文格式失败后能够在收尾阶段修复并返回说明，空知识部署得到明确表达。但是模型引用了不相关的 StatusMatcher 整页文本，故不能算用户任务验收通过；随后补原始页面引用拦截，只有本地回归，尚未证明开放语义引用都正确。

输出证据位于 `.secrets/user-failure-20260909/provider-recheck/`。本轮需要的数据接入、语义引用及正常浏览器完整验收保持未完成。启动 READY 只代表模型生命周期，不能作为业务可用/架构完成证据。未经真实用户场景验证，不再交由用户重复验收。
