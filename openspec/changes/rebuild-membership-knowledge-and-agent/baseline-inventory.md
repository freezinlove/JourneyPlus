# 现有存储与入口核对（2026-09-06）

本次只读盘点正式库，未执行结构升级。完整 31 张表的字段名、数量，以及 8 个旧活动的映射／方式／价格数量与事实签名保存在 [baseline-audit.json](baseline-audit.json)。不包含用户会籍内容、邮件正文或连接凭证。该文件是此次验收基线，不随日常采集自动更新。

## 字段职责和替代关系

| 表／字段组 | 当前用途及问题 | 新链路处理 |
|---|---|---|
| sources / source_items | 来源身份、external_id、URL、发布日期和增量元数据；URL 不等于活动身份 | 保留；LoyaltyLobby 日期门使用 published_at；邮件只发现活动链接 |
| document_versions | raw/normalized body、hash、parser、fetched_at；抓取日期不能充当活动生效时间 | 保留版本，切章节与证据；原文不是模型指令 |
| collection_runs / job_runs / automation_runs / initialization_runs | 运行状态、幂等键、计数、错误 | 后台诊断，不作为活动规则输入 |
| source_automation_states / automation_leases | 游标、日调度状态、租约 | 短事务更新，网络阶段不持有数据库连接 |
| statusmatch_watches / watch_pages | HOME/FAQ/Terms 当前文档、检查与错误 | 保留来源监控；关闭后 watch 可删除，知识层从事件 closure_document_version_id 接收关闭证据 |
| status_events | 项目、期次来源键、current_fact_set/current_brief、生命周期和关闭证据 | 映射 Activity；不能凭同项目或年份合并期次 |
| fact_sets.facts | what/eligibility/target/cost/window/caveats、并列 routes 与 mappings | 重新按来源提取方案、精确映射、费用；并列数组不能证明关联 |
| event_evidence / event_revisions | 来源链接、locator、旧版本历史 | 复用文档，定位新章节证据；URL-only 不当作精确引用 |
| analysis_runs | 输入版本、阶段、模型配置及结构化结果 | 提取／诊断记录，不能替代已发布知识版本 |
| article_analyses / article_opportunities | 一次文章解释及机会事实、期限、可见性、brief 指针 | 旧 LL 仅隔离验证；新 LL 写统一知识；多活动范围不明暂缓 |
| statusmatch_article_routes / article_supplements | 文章链接的官方项目及补充观点 | 来源身份与运行审计保留，第三方不变成官方规则 |
| briefs / article_briefs / statusmatch_change_sets | 旧派生摘要与变化；部分重复事实表达 | 新 CURRENT/UPDATE 从发布版本派生，不独立保存价格真值 |
| status_holdings | 用户明确保存的会籍和期限 | 保留身份，规范项目／等级；不能与旧文章一同排除 |
| agent_interactions / agent_wait_goals | 旧对话状态和等待条件 | 新临时工作区与独立确认等待任务；旧画像不得扩展 |
| review_decisions / gold_cases | 审核与评估记录 | 保留为后台用途，不默认注入 Agent |
| buy_points_snapshots / buy_points_offers | 买分独立业务 | 保持原业务，排除会籍匹配图和本次回填 |

完整字段清单见 JSON；新字段归属和约束仍按 database-design 执行。旧库里的 23 个文章机会均来自日期门之前，不能因为旧事实结构可读就正式回填。7 个现存官方监控和 1 个有关闭证据的旧事件属于需要核对的官方活动范围。

## 入口核对

- 每日与初始化调度：`automation/service.py`、`automation/initialization.py`；手动入口 `cli.py`。来源采集通过 `sources/collection.py::collect_in_phases`，官方检查通过 `statusmatch/monitoring.py::monitor_statusmatch_projects`；保存阶段仅使用内存预取结果，不能回退到实时网络。
- 官方提取：`statusmatch/project_workflow.py` 的分阶段入口，提取和旧兼容简报在事务外调用 Provider；普通文章：`article_operations.py` → `article_pipeline/phases.py`。补充文章：`statusmatch/article_workflow.py` 的分阶段入口。
- 新统一写入：`knowledge/refresh.py` → `knowledge/workflow.py` → `knowledge/publication.py`；当前仍受显式发布开关控制。校验和版本原子发布不等于完成所有数据回填。
- 旧消费者：`product/opportunities.py`、`product/briefs.py` 读取旧活动／文章 brief 指针；`membership/` 和 `statusmatch/graph.py` 使用旧映射贡献；`product/api.py` 的旧 AgentController 仍是旧接口。尚未切换，不能把新预览测试作为旧入口已修复的证据。
- 新消费者：`product/knowledge_api.py`、`agent/workspace.py`、`knowledge/reads.py`、`knowledge/routes.py`、`knowledge/briefs.py` 和 `/workspace` 预览。后续必须统一切换三入口，不能一部分用旧事实、一部分用新事实而无标识。

## 已确认的关联缺口

1. 旧映射、申请方式、价格数组缺少对应键；不得做笛卡尔组合或取最低价。
2. 同一目标项目可能有多期／多方案；项目名本身不是合并依据。
3. 普通文章正文可能介绍前置匹配；不能把背景活动的免费套给主体活动。
4. 采集失败、陈旧、结束是三个不同状态；关闭必须有 HOME 证据。
5. 现有旧简报与图来自不同投影；切换前必须核对同版本金额、条件和证据。
