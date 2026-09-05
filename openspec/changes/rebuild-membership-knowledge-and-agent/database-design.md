# 数据库、事实类型与发布详细设计

本文是 design.md D1–D4 的实施合约。业务对象及存储方向来自 [讨论原文](discussion-source.md)；字段、约束、并发与回填机制是本轮在已确认方向内确定的技术设计。实施者可调整命名，不得自行改变身份、归属、证据或未知语义。

## 1. 固定的组织方式

六类核心业务对象仍是会籍目录、活动、申请方案、来源文档、证据、用户会籍。物理表较多来自版本和多对多关系，不是多套知识库。四种披露视图不是四份数据表。路径是计算结果，简报是有版本的派生内容，StatusMatcher 不进入本节官方／文章知识模型。

主链固定为 Activity → KnowledgeVersion → OptionVersion → Mapping / Price；ApplicationOption 仅提供跨版本身份。SourceItem → DocumentVersion → DocumentSection → EvidenceReference 提供出处。KnowledgeVersion 经 ActivityDocument 引用此次采用的确切文档版本。

## 2. 类型和通用约定

下表未加 `?` 的字段必填；`?` 允许 SQL NULL。所有新记录 `id: UUID`，身份／运行表含 `created_at,updated_at: timestamptz`，不可变版本表仅需 `created_at`。枚举用有 CHECK 的字符串；复杂 JSON 使用 PostgreSQL JSONB，加 `schema_version=1` 并经严格 Pydantic 校验，拒绝额外字段。数据库 JSON 类型检查只能兜底，不能替代发布校验。金额 `numeric(18,4)`，API 序列化十进制字符串；日期精度见第 4 节。

## 3. 表及必要约束

| 表／作用 | 核心字段 | 约束与读取索引 |
|---|---|---|
| membership_programs | canonical_key:text、display_name:text、category:AIRLINE/HOTEL/CRUISE/OTHER、alliance?:text、metadata_provenance:JSONB | canonical_key 唯一；联盟仅归属；名称规范化检索索引 |
| membership_tiers | program_id:FK、canonical_key:text、display_name:text、rank?:int、rank_provenance?:JSONB | unique(program_id,canonical_key)、unique(id,program_id)；rank 无依据则 NULL，不跨项目比较 |
| membership_aliases | normalized_alias:text、program_id:FK、tier_id?:FK、locale?:text、origin:text | tier 必须属于 program；同一别名可对应多个对象；别名+program+tier 规范去重，检索 alias 索引 |
| activities | identity_key:text、primary_program_id?:FK、kind:STATUS_MATCH/OTHER、edition_key:text、current_version_id?:FK、merged_into_id?:FK | identity_key 唯一，合并不能成环；current 复合外键绑定自身 activity，初始允许 NULL；项目索引 |
| activity_knowledge_versions | activity_id:FK、version_no:int、base_version_id?:FK、status:DRAFT/VALIDATED/PUBLISHED/REJECTED、schema_version:int、facts:JSONB、fact_hash:text、source_hash:text、extraction_key:text、published_at?:timestamptz、validation_errors:JSONB | unique(activity_id,version_no)、unique(activity_id,extraction_key)、unique(id,activity_id)；published 后事实及子记录不可改；索引(activity_id,status) |
| application_options | activity_id:FK、logical_key:text、retired_at?:timestamptz | unique(activity_id,logical_key)、unique(id,activity_id)；表示一类持续的申请办法 |
| application_option_versions | knowledge_version_id:FK、activity_id:FK、option_id:FK、method:MATCH/CHALLENGE/OTHER、label:text、source_scope:JSONB、conditions:JSONB、challenge:JSONB、application_window:JSONB、status_validity:JSONB、action_link:JSONB、availability:AVAILABLE/UNAVAILABLE/UNKNOWN/CONFLICT | unique(knowledge_version_id,option_id)、unique(id,knowledge_version_id)；复合 FK 确保 option 与知识版本属于同活动 |
| option_mappings | option_version_id:FK、knowledge_version_id:FK、source_scope:JSONB、target_program_id:FK、target_tier_id:FK、conditions:JSONB、availability:枚举、evidence_ids:JSONB、semantic_key:text | unique(option_version_id,semantic_key)；目标 tier 复合 FK 校验 program；来源中的 ID 经发布校验；目标索引；版本复合 FK |
| option_prices | option_version_id:FK、knowledge_version_id:FK、target_tier_id?:FK、target_scope:EXACT/ALL_TARGETS、amount?:numeric、currency?:char(3)、known_state:枚举、fee_role:APPLICATION/CHALLENGE_SPEND/OTHER、charge_key:text、combination:REQUIRED/ALTERNATIVE/CONDITIONAL、alternative_group?:text、conditions:JSONB、raw_text:text、availability:枚举、evidence_ids:JSONB | amount≥0；EXACT 必须 target，ALL_TARGETS 必须无 target 且有通用适用证据；KNOWN 需 amount/currency；UNKNOWN 不填假 0；索引(option_version_id,target_tier_id)；版本复合 FK |
| option_price_mappings | price_id:FK、mapping_id:FK、option_version_id:FK | 主键(price_id,mapping_id)；两端必须同 option_version；用复合 FK 强制。价格 mapping_scope=EXPLICIT 时必须有行，ALL_MAPPINGS 时不得有行，scope 加在 price 上 |
| source_items（复用） | 现有来源、external_id、canonical_url、标题、发现／发布时间；增加 document_role:HOME/FAQ/TERMS/ARTICLE/OTHER | 保留现有唯一性和 URL 索引；SourceDocument 是领域名称，不重复创建同义表 |
| document_versions（复用） | 保留正文、哈希、parser_version、fetched_at、storage_mode、duplicate_of；增加 section_parser_version?:text | 原版本不覆写；来源许可继续约束 raw_body；解析版本变化可生成新定位版本，不让旧 evidence 漂移 |
| document_sections | document_version_id:FK、section_key:text、parent_id?:FK、kind:HEADING/PARAGRAPH/FAQ/TABLE/ROW/FOOTNOTE、ordinal:int、heading_path:JSONB、body:text、locator:JSONB、related_section_ids:JSONB、topics:JSONB | unique(document_version_id,section_key)、unique(id,document_version_id)；parent 同版本；索引(document_version_id,ordinal)；相关片段同版本校验 |
| activity_documents | knowledge_version_id:FK、document_version_id:FK、role:OFFICIAL_PRIMARY/OFFICIAL_SUPPORT/THIRD_PARTY、section_scope:JSONB | unique(knowledge_version_id,document_version_id,role)；空 section_scope 明确代表全文相关，不代表未定位；一文多活动各自限定片段 |
| evidence_references | document_version_id:FK、section_id:FK、locator:JSONB、quote:text、content_hash:text | section 与 document 复合 FK；同版本定位+内容签名去重；不存在精确位置的旧依据标为 DOCUMENT_LEVEL，不能伪造 section：此时 section_id 可 NULL，precision:SECTION/DOCUMENT_LEVEL 必填 |
| activity_briefs | knowledge_version_id:FK、brief_kind:CURRENT/UPDATE、previous_version_id?:FK、generator_version:text、status:PENDING/READY/FAILED、content:JSONB、fact_refs:JSONB、error_code?:text | unique(knowledge_version_id,brief_kind,generator_version)；UPDATE 前版同活动；无独立价格字段，content 数值位置用事实引用 |
| activity_observation_state | activity_id:FK 主键、last_checked_at?:timestamptz、last_source_changed_at?:timestamptz、last_error?:text、freshness:FRESH/STALE/INCOMPLETE | 运行观察可变，不嵌入不可变事实；当前状态不会因检查时间更新而产生事实版本 |
| knowledge_migration_links | legacy_table:text、legacy_id:text、legacy_path:text、target_table:text、target_id?:UUID、status:MAPPED/UNRESOLVED/REJECTED、reason:text、migration_version:text | unique(legacy_table,legacy_id,legacy_path,migration_version)；这是审计映射，target 类型由服务校验，不作为业务查询关系 |

OptionPrice 中 mapping_scope:ALL_MAPPINGS/EXPLICIT 是必填字段。没有明确对应证据时，不发布价格为普遍适用；可在草稿保留其原文与无法关联原因。多条价格是否同一次收费由 charge_key 表达，相同收费的多个来源只增证据，不叠加金额。

为 option_price_mappings 两端的复合外键，option_prices 和 option_mappings 均增加 unique(id,option_version_id)。价格 EXACT 目标必须出现在同方案目标映射集合中；绑定具体映射的目标还必须相符，由发布校验和写入服务检查。current_version 必须指向 PUBLISHED 版本，由切换事务及数据库触发器校验。

StatusHolding 保留现有表与 ID，增加 program_id、tier_id 复合 FK 和 revision:int；维持本地单用户每项目一条当前会籍。切换前规范化完毕，无法唯一确定的保留旧字段并标 NEEDS_CONFIRMATION，不能入正式路线起点。工作区和等待详见 [运行设计](agent-runtime-design.md)。

published 子记录的不可变性用数据库触发器或等价数据库写保护强制：更新／删除父版本为 PUBLISHED 的方案、映射、价格、文档关联时拒绝。只准切 current 指针；retired_at 仅控制身份管理，不改变旧快照是否存在。

## 4. JSON 合约：有限类型，不建通用规则引擎

`KnownState = KNOWN | UNKNOWN | CONFLICT | NOT_APPLICABLE`。不存在说明是 UNKNOWN；明确“无挑战”是 KNOWN/NONE；NOT_APPLICABLE 必须有业务原因。CONFLICT 不选一个值伪装确定。统一包装如下，known_state 替代冗余 conflict 布尔值：

```json
{
  "schema_version": 1,
  "known_state": "KNOWN",
  "value": "EARNED_ONLY",
  "raw_text": "示例：通过其他匹配获得的来源会籍不适用",
  "evidence_ids": ["evidence-uuid"],
  "alternatives": []
}
```

KNOWN 的 value 必填且有证据；UNKNOWN/CONFLICT 的有效 value 为 null，冲突说法各有 value/evidence_ids；NOT_APPLICABLE 的 raw_text 说明原因。引用必须属于本知识版本采用的文档且落在该活动 section_scope 内；发布事务前逐个检查，不只验证 UUID 存在。

| 类型 | 确定字段和语义 |
|---|---|
| SourceScope | kind:EXACT_TIERS/PROGRAM_ANY_TIER/CATEGORY_RULE/PUBLIC/UNKNOWN；program_id?、tier_ids[]、category?、rule_text?、evidence_ids[]。各 kind 互斥所需字段；PROGRAM_ANY_TIER 要有“任意等级”证据；CATEGORY_RULE 默认需核验，不自动扩大全目录 |
| ConditionSet | schema_version、items[]。每项 condition_id、topic、operator、value、known_state、raw_text、evidence_ids、effect:REQUIRE/EXCLUDE/INFORMATIONAL、supersedes_ids[]。topic 仅 SOURCE_ACQUISITION/RESIDENCY/MIN_REMAINING_VALIDITY/PRIOR_PARTICIPATION/DOCUMENT_REQUIREMENT/OTHER；operator 仅 EQ/IN/GTE/TEXT，类型与 topic 白名单匹配 |
| 条件继承 | 活动 facts.conditions → option.conditions → mapping/price.conditions 默认全部 AND；仅带证据的 supersedes_ids 可以替代指定父条件；不支持隐式覆盖或任意嵌套表达式。复杂 OR 保存 TEXT，评估 UNKNOWN；来源明确的多个不同办法才拆 option |
| Challenge | FactValue 的 value={kind:NONE/REQUIRED, metrics:[{unit:NIGHTS/STAYS/FLIGHTS/SPEND/OTHER,amount?,currency?,raw_text}],window:{anchor:APPROVAL/APPLICATION/FIXED/UNKNOWN,days?,end?:Temporal}}；缺指标不把 REQUIRED 改为未知有无挑战 |
| Temporal | precision:INSTANT/DATE/MONTH/RELATIVE/UNKNOWN、instant?:timestamptz、date?:ISO日期、month?:YYYY-MM、timezone?:IANA、anchor?:枚举、offset_days?:int、raw_text、evidence_ids。值字段互斥；来源只写日期且时区未知时不伪造精确 UTC 截止点 |
| ApplicationWindow | start:FactValue<Temporal>、end:FactValue<Temporal>；可计算时投影为带精度的日期／时间，事实仅保留一份 |
| StatusValidity | FactValue<{kind:FIXED_END/DURATION, end?:Temporal, months?:int,days?:int,anchor?:APPROVAL/COMPLETION}> |
| ActivityFacts | schema_version、title、summary:FactValue<string>、conditions:ConditionSet、lifecycle:FactValue<OPEN/UPCOMING/CLOSED>、application_window、caveats:FactValue<string>[]；细分方案有不同时间时以方案时间表达，不抹成活动统一期限 |
| Link | FactValue<{url,role:APPLICATION/INFORMATION}>；仅 HTTP(S) 可信来源链接；不从模型生成链接 |

条件是否满足单独计算为 PASS/FAIL/UNKNOWN，不与事实 known_state 混用。用户声称的来源取得方式仅是本次评估输入，不成为官方事实或永久画像。

## 5. 身份、版本、期次与价格归属

1. 同一来源已绑定活动且只是规则更新，延续 Activity。官方明确新一轮申请、资格重置或新的活动标识时新建 Activity；仅年份文字或品牌相似不足以合并。无法确认期次则保留草稿关联待核对。
2. 一个申请办法保持同一 logical option ID；改价格、截止期或部分资格产生新的 OptionVersion。航空会籍申请改成酒店会籍申请属于另一办法，新 option ID。删除办法是在新知识版本不再包含它，旧版本保留。
3. 发布版本包含该活动完整当前方案集合，不是零散 delta。每个引用固定知识版本；当前指针更新不重写旧会话。
4. Mapping 只描述已证实来源→目标；Price 必须属于同一 option，目标 EXACT 或有明确 ALL_TARGETS，mapping_scope 再约束来源适用。地区和附加资格在价格条件上继续检查，不在活动内取 min(price)。
5. 无法归属但正文确实有价格时，留草稿材料；允许其他已验证方案发布，当前版本的 caveats 标明存在未关联材料。对应未确证映射不得当正式可用边。

## 6. 发布与并发算法

采集沿用 source_items/document_versions；章节解析、提取和模型调用都在事务外。提取输入锁定 document_version_ids、上一 current_version 和 extractor/schema 版本，构造 extraction_key。草稿保存便于重试，校验通过才为 VALIDATED。

发布事务：锁 activities 行 → 检查 current_version == base_version_id → 检查文档关联、证据、版本归属、mapping-price 与事实类型 → 检查新签名 → 标版本 PUBLISHED 并写 published_at → 切 current_version_id → 提交。base 已变化时退出事务，重读新基线重新合并校验，不让晚到旧资料覆盖新知识。不能按 fetched_at 大小直接推断活动规则更晚。

fact_hash 覆盖有业务语义的规范事实，排除检查时间和重复证据；source_hash 覆盖确切证据集合。两者均不变不发布；仅 source_hash 变可发布证据更新版本但不生成 UPDATE 新闻；事实变才生成变化简报。A→B→A 属新版本，不使用全局 fact_hash 唯一约束阻止规则恢复。

发布后生成 CURRENT 简报，实质变化时另生成 UPDATE；以版本+种类+生成器版本幂等。失败只影响简报 status，当前活动卡可由事实确定性显示。重试扫描 PENDING/FAILED，复用现有每日调度，不引入队列服务。网络失败、辅助页缺失不改已发布生命周期；三页采集完整性与 HOME 关闭规则仍由源专用验证器执行。

## 7. 查询一致性与检索

提取草稿必须逐项返回 FactValue／方案／映射／价格及证据 locator，不能只返回一段总结。价格表确定性解析结果优先用于数值，模型不能改写已解析单元格；表格无适用关联时仍是未关联材料。正文复杂资格使用有限条件类型，无法无歧义表达则 TEXT/UNKNOWN。提取失败保留文档版本，不提交空事实覆盖旧事实。

冲突处理固定：先按同一期次、同一方案、同一时间适用范围对齐；不同适用范围拆清而不是标成矛盾。旧文档历史版本不与其替代的新文档混作两个当前规则。当前官方来源与文章冲突时官方规则用于确定判断，第三方说法作为标记补充触发核对；两个当前官方来源真实冲突时 CONFLICT，不能按文章多数、抓取时间或任意 HOME/TERMS 排序强选。仅当来源明确写明优先条款且有证据时采用其优先规则。活动关闭仍受 HOME 专用规则约束。

章节切分失败时，文档可保留一块 DOCUMENT_LEVEL 正文作为待定位材料，不凭模型想象生成行号；准确定位完成后创建新解析版本。旧证据不移动。DOCUMENT_LEVEL 可以支持解释“资料中有此说法”，但不能显示成精确条款定位，也不能为无法确定适用性的价格提供假精确证明。

一次查询开始在短只读一致性事务取得所有相关活动 current_version 与 holdings_revision，形成 snapshot_ref；之后所有查询固定该版本集合，事务外模型调用不持有数据库事务。缓存键包括排序后的版本集合、用户条件、holding revision、评估器版本；旧缓存只用于旧快照。

章节检索先用活动关联限制文档，再按显式证据／topic／标题和别名词匹配检索。中文采用应用层规范分词／别名展开并对限定活动的正文评分；首期不依赖 PostgreSQL 英文全文分词解决中文。精确事实引用优先于自由相关度；表格行总带表头和关联脚注，条款带父标题及例外，不能只截最短句子。

详情检索未覆盖全部相关章节返回 partial，抓取不完整返回 source_incomplete，覆盖内无说明返回 not_found_in_scope；均不是允许。相关章节超过预算以完整语义块分批，不截 JSON 或否定。

## 8. 现有存储到新模型的映射

| 当前结构 | 处理决定 |
|---|---|
| sources、source_items、document_versions | 保留采集身份、原文及哈希，增章节／role；不复制为第二套来源表 |
| status_events、fact_sets | activity + knowledge_version；current_fact_set 映射 current_version，保留历史事实及旧 ID |
| article_opportunities.facts | 按独立活动迁移同一知识模型；与官方确属同期才关联同活动，不能以 program 相同自动归并 |
| FactSet.application_routes | 提取 application_options / option_versions；scope 文字中的来源、地区关联只有证据充分才结构化 |
| FactSet.status_mappings | option_mappings；缺申请方式归属不能平均分给所有方案，留下 UNRESOLVED 和原文位置 |
| application_routes.prices | option_prices + 映射范围；无费用提及导致的旧 free 回填 UNKNOWN，金额不变但适用性未知也要降级 |
| event_evidence、event_revisions | evidence_references + activity_documents + 版本／审计映射；无法定位旧 locator 标 DOCUMENT_LEVEL |
| statusmatch_watches、watch_pages、change_sets | 保留源采集和变化诊断，关联 Activity；不是新的业务事实入口 |
| statusmatch_article_routes、article_supplements | 保留路由过程审计，将有效文章证据并入 activity_documents；补充观点保持第三方身份 |
| briefs、article_briefs | 保留旧历史只读；新 CURRENT/UPDATE 重新从新版本生成，不将旧文本提取回权威事实 |
| status_holdings | 保留 ID，补规范 FK／revision；待消歧不自动猜；不保存额外长期用户偏好 |
| agent_interactions、agent_wait_goals | 按运行设计迁移，旧临时交互提示重开，不强行解释为新版状态；等待业务条件保留并校验 |
| 运行、审核、gold、buy_points 表 | 不为此次 Agent 重构删除；后台范围及历史买分业务仍独立，不注入模型 |

顺序：备份与恢复演练 → 增表及兼容字段 → 身份／来源 → 方案及关联 → 影子发布 → 三消费者对照 → 统一新读开关切换。前期 Workflow 对同一文档继续旧写并生成新影子知识，两路失败独立记录；切换后新知识为权威，不用旧模型回写污染新事实。切换开关统一选择知识底座，不能简报新库而图旧库无提示。

回滚保留新表且切回已验证旧读服务；会籍／等待写入保持兼容的 ID 和业务操作日志（仅这两种显式业务数据），重放到回退服务后再开放写入；演练需覆盖切换后新增和修改。若旧逻辑仍有已知费用缺陷，回滚不能恢复“可信推荐”承诺，应关闭受影响推荐并保留资料浏览。退役是后续受控迁移，不能为了干净先删除历史。
