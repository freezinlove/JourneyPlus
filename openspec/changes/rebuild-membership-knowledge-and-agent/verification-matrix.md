# 实施与验收追踪

本表对应十二份能力规格及 U01–U23 决策；机器原始记录位于私有验证目录，不把完整对话、用户会籍或来源 HTML 加入公共夹具。

| 能力规格 | 主要回归入口 | 真实验收与边界 |
|---|---|---|
| unified-activity-knowledge | test_knowledge、test_catalog_identity、test_catalog_metadata | PostgreSQL 约束、目录身份衔接；历史 ID 保留，普通歧义别名不等价 |
| versioned-source-evidence | test_knowledge、test_statusmatch_tables、test_source_conflicts | 真实 FAQ 表格／脚注定位；独立来源冲突发布；StatusMatcher 来源拒绝进入官方库 |
| knowledge-publication-workflow | test_knowledge_refresh、test_price_quarantine、test_statusmatch_short_transactions | 八项官方活动隔离回填、Kenya/Vietnam 最新读回及无模型幂等；17项费用缺口仍未知 |
| progressive-agent-data-access | test_knowledge_transport、test_knowledge_pagination、test_token_budget、test_packet_format_evaluation | 36次真实格式实验、候选覆盖及展开；首批少传，不声称遍历全部更便宜 |
| conversational-membership-agent | test_workspace、test_completion、test_workspace_evaluation | 35项开发任务和10项保留任务；首个保留集8/10，失败修复后重复运行属于回归 |
| temporary-agent-workspace | test_workspace、test_route_browsing、test_read_basis | 真实刷新、旧卡、到期新建、取消保存、话题切换；独立等待不随工作区删除 |
| membership-route-evaluation | test_knowledge_routes、test_route_evaluation、test_catalog_identity | 真实价格／挑战／条件复核；来源索引与循环防护；完整已发布图仍可能有知识缺口 |
| activity-briefs-and-exploration | test_activity_cards、test_brief_changes、test_route_details | 三入口版本／费用一致、变化与历史；旧文章仅隔离验证 |
| agent-result-presentation | tests/js/route_graph.test.mjs、test_presentation_nodes、test_comparison | 桌面与390px浏览、旧链接精确详情、筛选Aer Lingus三条映射及护照脚注；浏览零模型 |
| scoped-statusmatcher-research | test_research_http、test_report_pages、test_step_research、test_research_cache 等 | 固定页面＋受控HTTP＋真实库／页面联动；实际StatusMatcher网络许可关闭，不能宣称生产网站已读通 |
| confirmed-membership-waiting | test_workspace_wait_semantics、test_agent_automation、test_user_journal | 每日零命中零模型、首次展示后停止、幂等确认、独立任务恢复；会籍／等待增量重放 |
| knowledge-migration-and-evaluation | test_knowledge_compatibility、test_knowledge_rollout、test_user_journal、迁移回归 | 备份恢复、0024往返、新增会籍与等待重放、旧入口及影子差异；正式切换／稳定观察／退役未执行 |

## 收尾证据

- 全量确定性回归收集678项：677通过、1跳过；之后详情来源名称批量读取的74项专项中73通过、1跳过。JS图结构3项通过。
- 最新 PostgreSQL 空隔离 schema 中，目录身份／路径／来源冲突／未知费用共22项：21通过、1按测试条件跳过。所有测试事务回滚，临时 schema 随后清理，不影响副本 public 数据。较早误把要求空库的测试放进有历史库存的副本、以及空 schema 未建表两次失败不作通过依据。
- 首次10项保留集的失败分别为 Provider 超时与长步骤名称下关闭提示缺失。其后暴露目录循环、无命中被误报预算失败、可选目标被当作必填等问题，均保留失败记录。公开入口、来源名单声明、经验关闭、单／双目标路径和新Vietnam身份场景分别真实重复三次通过。
- `evaluation-vietnam-indexed-final.json` 三次真实 Provider 通过，32.98／44.53／34.01秒；明确只列 Gold 路径，费用未知、USD149仅为中间已知费用，资格／挑战未知保留。
- `shadow-read-indexed.json` 在含一条额外恢复测试会籍的副本：39条旧图边，105条新路线、36个共享步骤；109个搜索状态、177次相关映射检查。已发布图搜索完成，但Flying Blue来源映射缺口使整体仍为PARTIAL。旧边与新路线计数不直接相减。
- `official-footnotes-final/readback-and-idempotence.json`：Kenya 184条，Vietnam 175条；两项重复回填REUSED、0模型、0新增简报。74个官方事件／历史事实版本入口可解析，24个旧文章入口ARCHIVE_ONLY。
- `final-scope-check.json`：配置库仍31表、0018，2条会籍／1条等待；原验证库仍50表、0023，2条会籍／3条等待。默认legacy、知识发布false；没有提交Git、迁移正式库、切换默认消费者或开启真实经验网站。

## 尚未满足的发布条件

12.6的正式发布部分与12.8继续未勾选。需按恢复手册完成正式库备份、当前官网状态复核、正式迁移／消费者切换及后续稳定观察；不能把测试副本直接替换正式库。旧存储退役、主规格同步和change归档在这些条件完成后进行。

模型预算续页保护另有53项专项通过；新增一项回归后当前总收集679项，不把新增项冒充已在此前678项全量运行中通过。真实首页三档预算结果见packet-page-reference-readback.json。
