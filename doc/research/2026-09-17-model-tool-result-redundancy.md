# 返回给模型的工具结果冗余审查

日期：2026-09-17。范围：模型实际消息构造，不讨论数据库表能否删除。仅研究，未改运行逻辑。

## 1. 核对路径与证据边界

核对 `agent/harness/runtime.py`、`harness/context.py`、`tools/projection.py`、`adapters/activity_access.py`、`adapters/model.py`。

工具结果先存完整归档；经过活动可见性处理、工具自有 model_projection、上下文处理后，最终由 wire_result 序列化进模型工具消息。原生协议和 JSON 协议都使用 wire_result。当前运行使用原生协议。

已存在的精简：

- wire_result 去掉顶层 metrics、call_id、空 error/next_cursor/provenance/effective_input/artifact_refs、默认未命中 cache。
- coverage.data_path 被移除；full_result_ref 与顶层 artifact_refs 的重复项被去重。
- holdings.read、holdings.write、waiting.manage 有自有精简：去掉 source_record、display_statement、name_authority、conditions_schema_version；写入结果转为实体当前状态及变化摘要，不再给完整 before/after；去掉这些工具的 effective_input。
- 上下文已有严格相同只读结果去重，以及容量不足时的历史索引机制。不是所有工具结果永远完整重复发送，也不是任意相似查询都会被去重。

实测样本：汉莎匹配图这一轮持久化的 11 条工具消息，套用当前 wire_result 重建单条紧凑 JSON 的 UTF-8 字节数。它不是供应商原始 HTTP 抓包、不是 token 数，也不是整轮累计传输量。当前轮上下文还可能经过可见性/去重/容量处理。最后 display.present complete=true 结束该轮，其回执主要影响以后轮次，不应算作本轮最后一次模型输入。

| 结果 | 重建字节数 |
|---|---:|
| activity.read 映射参数错误 | 420 |
| catalog.lookup 汉莎目录 | 1,430 |
| activity.read 空概览 | 348 |
| routes.evaluate 缺少来源 | 2,944 |
| catalog.lookup 空目录 | 382 |
| activity.read 8 个活动的来源目录 | 17,436 |
| activity.read 空详情 | 346 |
| routes.evaluate 再次缺少来源 | 3,164 |
| routes.evaluate 来源等级歧义 | 3,838 |
| routes.evaluate 6 条路径 | 6,207 |
| display.present 回执 | 3,931 |

前 10 条合计 36,515 字节，其中来源目录占约 47.7%。这是各结果单次大小之和，历史结果在后续调用中会再次进入上下文。不要据此推算延迟同比下降。

## 2. 路径查询：最值得优先精简

### 必须直接保留

- 明确状态：是否具备查询条件、是否完成路径搜索、缺失条件或歧义候选。
- effective_query 的有效语义：来源/目标、等级、保存会籍或显式身份模式、继承的筛选条件。query_ref 用于继续修改原查询。
- 解析结果中会影响理解的差异或不确定性；过期/排除的会籍及原因；保存会籍的时效判断。
- 每条路径的可调用 ref、节点顺序、免费/付费、constraint_match、未知条件和需要检查的实质限制。
- 分页游标、未读候选、搜索范围、知识不完整与查询未完成的区别。
- 一个可读取完整结果的 full_result_ref。

### 可以从默认模型消息去重或移出

| 字段 | 判断与保留条件 |
|---|---|
| data.route_refs | 样本中与 candidates[].ref 完全重复。6 条路径重复引用占 427 字节；默认留候选对象内 ref 即可。 |
| data.query_context.changes、field_origins、source_message_refs | 普通一次查询不需反复带完整审计。样本 716～856 字节。涉及继承歧义时可按需读，默认保留 parent_query_ref 和必要变化说明即可。这些来源标记不证明用户授权，不能拿它代替用户原话。 |
| query_context.inheritance、origin_scope | 通用解释每次重复。移到一次性工具说明/系统说明；不同查询的具体语义仍保留。 |
| effective_input 与 effective_query | 不是直接删其一：前者可能包含默认值/标准化结果。默认提供一份权威有效查询，加上实际解析差异；不要原始、有效、解析身份三套全量复述。 |
| resolved_* 中 ref/tier_ref、ref/program_ref | 同一个身份重复引用，保留一个可用 ref。候选共同的 program/alliance/category 提到公共层；不能删等级候选。 |
| coverage.returned 与 returned_count | 样本同义计数，合并。offset/page_offset 不能盲删：多段快照分页时可能含义不同，默认模型通过游标续读，一般不需要内部两个偏移。 |
| search_complete 与 searched_published_graph_complete | 当前 coverage 函数前者由后者生成，可合并权威字段；但 knowledge_complete 和 retrieval_complete 不同义，不能顺手删掉。 |
| checked_edges、expanded_states | 算法诊断，默认不提供给模型。 |
| search_metrics 的分类总数与重复 scope | 过滤诊断按需读；如果存在 UNKNOWN/排除结果影响“全部匹配”的结论，必须保留说明。搜索语义限制集中表述一次。 |
| artifact_refs 中已在 query_ref 等位置出现的引用 | 去重即可，不能删除唯一能用于后续读取的结果集合引用。 |

缺少条件时尤其不应返回一大套看似“搜索完毕”的零计数。当前样本空路径结果仍约 3 KB；其中 query_context 716 字节、search_metrics 240 字节、coverage 720 字节。应首先突出“未完成查询，不能判断是否有路径”。字段矛盾是语义问题，不能仅靠删除文本修复。

## 3. 目录查询

样本汉莎只有一个项目，aliases 返回 9 条，包括正式名称重复出现、大小写变体，以及每个别名的 origin 和空 locale。

- 保留项目名、可用 ref、用于消歧的等级候选、必要的类别、是否还有候选。
- 默认别名仅保留有助于确认匹配的名称；同名/仅大小写不同项去重，origin 枚举和空 locale 不必全部给模型。
- 不能把候选等级全删：正是这些等级告诉模型需要进一步确定来源身份。
- has_more 与 next_cursor/分页覆盖信息集中一处即可；不能从空候选推断活动或路径不存在。

## 4. 活动读取

本轮 evidence 视图已是来源目录，不是原文全文。17,436 字节主要因为一次读取了 8 个活动。应区分“调用范围过宽”和“返回字段重复”。

可精简的具体项：

- 当前版本记录中 current_version_ref 与 version_ref 一样，可只留 version_ref + is_current；历史读取时保留版本差异。
- 顶层 provenance 只重复各活动版本号，样本 585 字节。可集中声明 workflow 来源，各条仍保留版本绑定。
- material_ref、brief_section_ref、mapping_table_ref 不应所有视图无差别展开。保留当前任务需要的入口及一个完整材料入口，并给出可扩展章节；不能要求模型自行拼接引用。
- summary.source_links 与 evidence.catalog 的相同 URL 可合并；唯一来源必须保留。
- source directory 的空 facts/caveats/expansions 和每个活动重复的“尚未读原文”说明可集中一次，但“只是目录、尚未核验正文”必须显著保留。
- document_version_ref 与可独立定位该文档版本的 section_ref 在该样本重复；默认可只留可用 section_ref。需要跨文档版本比较时保留版本元信息。

不可裁掉：资格、费用、有效期、冲突、未知状态、适用范围、表格维度、映射关系、具体来源 URL 和版本证据。原文已被用户/模型明确请求时，不能以“精简”为名改成无说明的摘要。

## 5. 其余工具（代码审查，非本轮实测）

| 工具 | 应留给模型 | 可精简内容 |
|---|---|---|
| holdings.read | 会籍名/等级/引用、有效期及有效状态、身份不确定性、快照引用 | 已有 projection；再核对 snapshot_ref 与顶层 refs 的同值重复即可，不能删除有效性信息。 |
| holdings.write / waiting.manage | 成功与否、outcome、实际变更、实体状态、冲突版本、唯一操作回执 | 已有 before/after 精简，不是本轮重点；错误候选/冲突资料不能套用成功裁剪。 |
| workspace.read | 模型主动请求的历史、材料、引用、分页范围 | data.next_cursor 与顶层游标可统一；不能默认将明确读取的全文又替换成摘要。 |
| workspace.note | 保存结果、note_ref、revision | 去重引用；本身体积小。 |
| web.search | 搜索结果、标题/URL/摘要、覆盖限制和游标 | data.coverage/next_cursor 与顶层字段有重复传递，统一一份；保留检索覆盖有限的事实。 |
| web.read | 请求正文、引用、URL/重定向信息、来源时间含义、截断与未读部分、可继续读取入口 | 相同 url/final_url、page_ref/snapshot_ref/artifact_refs、cache_hit 与 cache、通用证据说明重复可合并。content_hash、retained_raw_bytes 通常是诊断/完整性记录，默认按需；raw_truncated 不能删。链接需先保留相关性和进一步调查能力，不一刀切去掉。 |
| display.present | 是否生成展示、presentation_ref、图类型与对象范围、失败/遗漏 | answer 与已提交参数重复，effective_input 重复整份输入；样本 effective_input 1,654 字节、answer 870 字节。默认简短回执，后续可按 ref 查完整内容；生成成功不等于客户端可见，失败的客户端反馈仍应保留。 |

## 6. 总体建议

优先级：路径状态与重复结构 → 目录别名 → 活动视图按需入口/去重 → 展示回执 → 联网工具的重复封装。会籍写入已有精简，先保持。

实现应放在工具自有 model_projection/最终模型消息层，保留完整归档与可展开引用，不改业务数据结构。按工具与状态区别处理，不能全局删除所有空值（某些空值表达未知/清除条件），也不能为省 token 隐去证据缺口。

验证应比较精简前后模型是否仍能：澄清缺失等级；保留多轮筛选；分页读完；区分无结果与未执行；展示实际路径；打开固定版本；理解 UNKNOWN；报告写入成功与失败；按引用取回原始证据。先用真实样本做信息保真检查，再测多轮模型表现与耗时。不能先承诺节省百分比或固定调用轮数。
