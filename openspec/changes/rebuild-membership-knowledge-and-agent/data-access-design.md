# 渐进披露、路径评估与工具契约

本文件固定服务端如何选数据、模型收到什么和怎样补查，对应 D5/D6。字段为一期核心合约，schema_version=1，额外字段拒绝；下述引用在服务端映射 UUID，模型不能指定数据库 ID、任意 URL 或 SQL。

## 1. 共同返回信封

三个读取能力返回 `schema_version, status, snapshot_ref, data, coverage, caveats, expansions, provenance`。status 为 OK/AMBIGUOUS/PARTIAL/NEEDS_INPUT/UNAVAILABLE；经验另有独立研究状态。coverage={search_complete:boolean, scope_description:string, observed_count:int, returned_count:int, presentation_has_more:boolean, stopped_reason?:string}。observed_count 仅表示实际搜索范围；无完整搜索不能显示全局总数。

provenance 是短引用与文档类型、名称、资料时间，不默认含完整 URL。expansions=[{ref,kind,aspects,reason}] 是可请求对象清单。caveats 放改变结论的限制和未知，不能由模型省略后再给无条件推荐。snapshot_ref 对应工作区版本集合与评估上下文；新问题可新建快照，旧引用不变。

## 2. query_activity_materials

输入：`selector:{ref?:string,text?:string}` 至少一个；`question:string`；`view:AUTO/OVERVIEW/DETAIL/EVIDENCE/CHANGES`；`aspects: PRICE/ELIGIBILITY/CHALLENGE/WINDOW/VALIDITY/STATUS/APPLICATION/CHANGES[]`；`evidence_refs:string[]=[]`；`cursor?:string`。known context 由服务注入，不让模型重填已知会籍或版本。ref 与 text 明显不一致返回歧义，不任选。

定位顺序：当前有效引用 → 规范项目／活动别名 → 项目下当前期次候选。唯一才读，多个返回最多 5 个有期次／来源区别的对象和 continuation，不能总取第一个；仅项目名也不把全部年份合成一个活动。活动定位和正文查找属于同一能力。

data={activities:[{ref,name,edition,version_ref,lifecycle,freshness,summary,material_caveats}],facts:[{ref,subject_ref,field,known_state,value,text,evidence_refs}],snippets:[{ref,document_label,heading,text,related_refs,precision}],changes:[{field,before,after,reason,evidence_refs}]}。只填本问题必要数组。金额不适用未知保留；正文带上下文，和 facts 冲突时并列而非让模型任选。

AUTO 规则：概括问返回身份+关键条件；金额先精确方案价格；资格细节先相关事实并带证据；用户明确原文直接 EVIDENCE；最近变化锁定同活动相邻事实版本。任意自然语言不能只靠关键词路由，Agent 给方面，服务端用问题和明确事实引用检索。

## 3. query_membership_routes

输入：`mode:EXPLORE/COMPARE/INSPECT`；`query?:RouteQuery`；`route_refs:string[]`；`aspects:string[]`；`cursor?:string`。INSPECT 最多批量 3 条路线，一次读所需价格、资格、挑战和证据，不分拆成逐字段模型往返。EXPLORE 可以没有目标或 holdings，公开机会单独组；COMPARE 可以是已展示路线。

RouteQuery={target?:{program_ref?,tier_ref?,alliance?,category?},budget?:{kind:FREE/CAP,amount?:decimal,currency?:ISO},allow_challenge?:boolean,preferences:FEWER_STEPS/LOWER_KNOWN_FEE/LESS_UNCERTAINTY[],temporary_context:{source_acquisition?,residency?,prior_participation?}}。相互冲突的条件先澄清；“高卡”无法规范时不猜等级。用户未说免费或拒绝挑战时不默认加约束。residency 只用于用户明确提供后的适用性评估，不从语言／IP 推断。

data={query_summary,groups,cards,steps,reason_counts}。card={ref,name,from,to,step_refs,step_count,classification:MATCH/NEARBY/UNKNOWN,cost,challenge,window,validity,constraint_checks,material_caveats,fact_refs,needs_inspection}。steps 是共享步骤表，每个 step_ref 仅定义一次，带 readable from/to 和 option/activity 引用。概览无完整步骤正文；detail 才展开。

cost={state:KNOWN/PARTIAL/UNKNOWN/CONFLICT,totals:[{currency,amount,role}],conditional_items:[],alternative_items:[],is_proven_free:boolean,scope:text}；不同币种各列，条件费用不算成确定总价。challenge={state:NONE/REQUIRED/UNKNOWN,unresolved_steps:[]}。期限逐步保留，只有可比较精度和时区才求最早硬截止；有效期不简单取最大值。

## 4. 确定性评估顺序

1. 取快照、标准化持有会籍（过期不可作正式起点），检索相关 STATUS_MATCH 可用映射；公开来源是独立入口。文章与官方经相同服务读取。
2. 每扩展一个 option mapping，合并活动、方案、映射条件。计算来源资格和未来步骤取得方式：匹配获得的中间会籍标 MATCHED，不冒充 earned。时间／材料等不能判断时 UNKNOWN。
3. 匹配价格先验证 option_version、目标范围、mapping_scope，再评估 price.conditions。只有已知唯一适用的必付收费组或明确累计组才加入确定金额；未判明的选择保留备选／未知，禁止取 min。
4. 条件判断返回 `{condition_ref,result:PASS/FAIL/UNKNOWN,actual,expected,reason,fact_refs}`。某已知必付金额已超 cap 即 FAIL；未超但其他收费未知为 UNKNOWN。拒绝挑战遇 REQUIRED 即 FAIL；全步骤 NONE 才 PASS。任何 UNKNOWN 不因为另一步 PASS 消失。
5. 全部显式硬条件 PASS 才为 MATCH，但未完全可计算的申请资格仍以 caveat 列出，不承诺可获批。只差一个可调整的用户条件且其他条件 PASS 为 NEARBY；其余关键未知为 UNKNOWN；两项以上失败不伪装单条件近似方案。活动关闭或来源不接受等事实不能作为“可放宽的用户偏好”。

## 5. 搜索、去重与短名单算法

搜索状态含当前位置、步骤列表、已访问节点、累计已知费用、来源取得方式、继承限制和事实引用。采用有界队列枚举相关可行／未知状态；按步骤数、已知支出及稳定 ID 的确定顺序推进，只是枚举顺序不是最终推荐分数。同节点的不同取得方式和限制不能合并。

初始技术预算：10,000 次状态展开、20,000 次边检查、2 秒服务端路径计算，任一先到则 partial；这是校准值，不是最长六步产品规则。有限图中同路线重复会籍节点先剪环，若存在证据说明重复取得有不同资格意义则作为独立资格状态而非绕过防环无限搜索。每个停止原因写 coverage。

去重键为完整 ordered option_version + mapping + 适用价格组 + 影响后续资格的条件，不是仅 node_path。共享步骤只存一次。严格支配要求同目标、同适用性与不确定性、无额外限制、费用可比较且不更高、挑战和步骤不更差，并保留不同来源历史与 visited 集合影响；不能证明时不剪。被折叠候选保留服务端引用和折叠原因。

短名单先按目标与 MATCH/NEARBY/UNKNOWN 分组，再轮转选取各组费用已知较低、步骤少、无挑战、有不同关键限制的代表，重复代表去重，余量按稳定排序填充。默认 8、最多 12。组多于预算先返回目标组概览并要求展开，不能让排在后面的整个类别永久消失。页游标绑定 snapshot、query_hash、排序和位置并签名；快照失效返回 EXPIRED，不重用游标指向新数据。

最终推荐至多 1+2 由 Agent 在已验证引用中选取；探索仍能按组／游标继续。不允许通过省略 needs_inspection 把未核实候选升级为正式无条件推荐。

## 6. 输入预算与加载策略

上下文由 system/action schema + 当前消息 + 最小工作区 + 当轮工具包组成；不序列化历史完整活动／图／HTML。闲聊业务工具包为零。最近最多 6 轮短期消息作为起始窗口，仅当前焦点摘要和必要未决问题随包；更早细节从工作区对象按引用恢复，不能靠摘要发明。

比较数据目标预算 5,000 token，聚焦 7,000；全文系统上下文需额外计入 Provider 上限。优先用与 Provider 匹配 tokenizer；无 tokenizer 时使用实测中文 token/字节分布的保守上界估算并标 estimate，调用后以 usage 校准。不能把固定字符÷4当准确值。

超预算顺序：去内部元数据／重复字段 → 共享步骤 → 删除与问题无关方面 → 缩减组内重复候选并保留 continuation → 分批章节。关键否定、条件、脚注不可压短改变语义；一个对象相关材料仍装不下，返回 needs_inspection 和余下引用，禁止强答。不调用第二个摘要模型。

三次模型调用的批量路径：第一次选择资料／路径能力 → 程序返回比较包 → 第二次选择最多 3 个对象的多个方面及可选经验 → 程序批量执行 → 第三次回答。若第三次仍缺信息，答可用部分并续接；不得再偷偷补一次模型。修复占用同预算，具体降级见运行设计。

## 7. 模型输入实例（合成数据，不是实际报价）

```json
{
  "schema_version": 1,
  "status": "OK",
  "snapshot_ref": "Q1",
  "data": {
    "query_summary": "示例 A Gold 出发，不接受挑战",
    "cards": [
      {"ref":"R1","name":"A Gold → B Silver","from":"A Gold","to":"B Silver","step_refs":["S1"],"step_count":1,"classification":"MATCH","cost":{"state":"KNOWN","totals":[{"currency":"EUR","amount":"100.0000","role":"APPLICATION"}],"conditional_items":[],"alternative_items":[],"is_proven_free":false,"scope":"仅航空会籍方案 Silver 档"},"challenge":{"state":"NONE","unresolved_steps":[]},"material_caveats":["来源会籍须非匹配取得，用户尚未说明"],"needs_inspection":false,"fact_refs":["F1","F2"]}
    ],
    "reason_counts": [{"reason":"明确要求挑战","count":1}]
  },
  "coverage":{"search_complete":true,"scope_description":"合成示例中的两种方案","observed_count":2,"returned_count":1,"presentation_has_more":false,"stopped_reason":null},
  "caveats":["MATCH 仅表示不挑战这一已声明查询条件满足，申请资格仍待确认"],
  "expansions":[{"ref":"R1","kind":"ROUTE","aspects":["ELIGIBILITY","EVIDENCE"],"reason":"核对来源取得方式"}],
  "provenance":[{"ref":"F1","document_label":"Terms · Silver 价格","observed_at":"2026-09-05T00:00:00Z"}]
}
```

这是按问题投影的最小实例，省略字段不能被前端当作无要求；实际契约对 view 规定必填投影。若用户已明确来源 MATCHED，则 R1 因资格失败排除；若查询明确要求资格已证实，则该未知必须进入 UNKNOWN，而非 MATCH。
