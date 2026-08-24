## 审核范围

- 审核日期：2026-08-24（Asia/Shanghai）
- 输入：本地 PostgreSQL 中 8 个 ACTIVE StatusMatch watch 的当前 FactSet
- 真实项目：Air Astana、Club Avolta、Enrich、Flying Blue、GHA DISCOVERY、Kenya Airways、Royal Jordanian、Vietnam Airlines
- 重复命令：
  - `.venv/bin/journeyplus statusmatch-graph-audit`
  - `.venv/bin/journeyplus statusmatch-graph "Air France Flying Blue" Gold`
  - `.venv/bin/journeyplus statusmatch-graph "GHA Discovery" Platinum --max-depth 6 --max-nodes 100 --max-branches 15`

## 事实忠实度结果

- 当前项目：8
- 规范项目：128
- 会籍节点：417
- 聚合后的确定边：1,166
- 通配规则：2
- 未明确等级规则：0；当前真实数据没有此类关系，`UNCERTAIN` 展示与查询行为由专门 fixture 验证
- 可用/条件 mapping claim：1,176
- 明确不可用 mapping：208，全部未进入可达边
- missing claim：0
- invented claim：0
- duplicate claim ID：0
- mapping material mismatch：0
- direction mismatch：0
- missing evidence：0
- 条件边：98
- 自环：0
- 项目别名歧义：0

审计器会重新从每个 claim 指向的 FactSet 读取 mapping 索引和来源等级索引，比较来源项目、来源等级、目标等级、availability、conditions、conflict 和 evidence；随后检查 claim 所在边的 source node alias 与 target node alias，避免只比较数量而漏掉箭头反向。

## 人工原页核对

### Flying Blue Gold → Nomad Club Gold

- 图 claim：`Air France Flying Blue / GOLD → Nomad Club GOLD`，来源 Air Astana FAQ。
- 原页可见表头为 `AIRLINE | SILVER | GOLD | DIAMOND`。
- `Air France Flying Blue` 行中，`SILVER` 位于 SILVER 列，`GOLD / PLATINUM / ULTIMATE` 位于 GOLD 列，DIAMOND 为不可用。
- 结论：图中 Gold → Nomad Gold 的方向和等级正确；没有把 Nomad Gold 反向指向 Flying Blue Gold。

### Club Avolta 通配关系

- 原页第一张表明确为 `Airline | Eligible for Gold status`，内容为 `All major airlines | All membership levels`。
- 原页第二张表明确为 `Hotels | Eligible for Gold status`，内容为 `All major hotels | All membership levels`。
- 图只保存两条类别通配规则；查询已知 AIRLINE/HOTEL 节点时按需解析，并标记 `WILDCARD` 和 `derived_from_rule=true`。
- 特别回归：`Accor ALL` 是品牌名，不再因末尾 `ALL` 被误判为通配来源。
- 特别回归：Air Astana Nomad Club 只作为当前图目标出现，不能从其他来源表继承类别；项目名中明确的 `Air` 现将其确定性标为 AIRLINE，因此 Nomad Club Gold 也能命中“所有主要航司”规则。

### 条件关系

- Flying Blue FAQ 原页脚注明确写明 Platinum 在部分国家不可用，并允许符合条件的顶级申请者选择 Gold 或 Platinum。
- 对应 Platinum 映射保留 `CONDITIONAL` 和脚注全文条件；它可以显示为候选边，但不会伪装成无条件关系。

### 真实闭环

审计发现一个强连通分量：`GHA DISCOVERY Platinum`、`Lotusmiles Titanium`、`Royal Jordanian Silver Jay`。逐页核对如下：

- Vietnam Airlines FAQ 的 HOTEL 表头为 `HOTEL | TITANIUM | GOLD | PLATINUM`；`GHA Discovery` 行把 `Gold / Platinum` 放在 TITANIUM 列，因此 `GHA Platinum → Lotusmiles Titanium` 正确。
- GHA FAQ 的 AIRLINE 表头为 `AIRLINE | PLATINUM | TITANIUM`；`Vietnam Airlines Lotusmiles` 行把 `Gold / Titanium` 放在 PLATINUM 列，因此 `Lotusmiles Titanium → GHA Platinum` 正确。
- Royal Jordanian FAQ 的 Hotel 表头为 `Hotel | Silver Jay | Gold Sparrow | Platinum Hawk`；`GHA Discovery` 行把 `Gold / Platinum / Titanium` 放在 Silver Jay 列，因此 `GHA Platinum → Royal Jordanian Silver Jay` 正确。
- Vietnam Airlines FAQ 的 AIRLINE 表中，`Royal Jordanian Royal Club Silver JAY` 位于 TITANIUM 列，因此 `Royal Jordanian Silver Jay → Lotusmiles Titanium` 正确。

结论：闭环来自真实活动表格，不是程序把箭头接反或别名误合并。底层图必须保留这些事实，产品树视图负责截断。

## 树状逻辑审核

### GHA Discovery Platinum（默认限制）

- 第一层分支：4（Club Avolta Gold、Asante Rewards Gold Elite Plus、Lotusmiles Titanium、Royal Jordanian Silver Jay）
- 节点出现：18
- 实际展开节点：7
- CYCLE：1
- CROSS_REFERENCE：9
- 截断：0

`GHA Platinum → Lotusmiles Titanium → GHA Platinum` 的回边显示为 `CYCLE` 叶子，不再生成 children。共享的 Club Avolta、Lotusmiles 和 Asante Rewards 子图只完整展开一次，后续均为 `CROSS_REFERENCE`。

### Flying Blue Gold

- 默认限制：第一层 3 个分支、18 个节点出现、6 个实际展开、9 个交叉引用、7 条因深度限制省略。
- 深度 6 审核：28 个节点出现、10 个实际展开、1 个 cycle、16 个 cross-reference、0 个静默截断。

默认结果优先保持短而清晰；提高深度后可以看到真实闭环，但仍是有限树。所有 children 按目标项目、等级和 certainty 稳定排序，相同 FactSet 重复查询结果完全一致。

## 人工判断

1. **关系指向符合提取事实。** 抽查的精确、条件、通配和闭环关系均与原始表格列方向一致；全量机器审计也未发现 material 或 direction mismatch。
2. **底层图存在真实环，但用户结果不会成为闭环网。** 树查询使用当前路径祖先检测、全局已展开检测以及深度/节点/分支上限；环被保留为可见叶子，重复子图变成交叉引用。
3. **复杂度目前可接受。** 代表性根节点第一层分支为 3–4，真实复杂性主要被 cross-reference 折叠；默认深度会主动截断长链并报告数量。没有隐藏丢边或无限递归。
4. **图表达的是公开的等级映射机会，不等于用户一定符合申请资格。** 每条 claim 保留活动、条件、冲突和证据；地域、费用、一次性申请等仍应由活动 FactSet/简报展示，不能仅凭路径自动下结论。
