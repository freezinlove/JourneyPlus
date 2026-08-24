## Why

StatusMatch 专门链路已经保存了真实项目的标准化会籍映射，但目前只能按活动逐项阅读，无法回答“给定一个会籍，接下来可以匹配到哪里、还能继续匹配到哪里”。第二阶段需要把这些事实映射组织成可查询、可审计且不会因共享节点或反向关系变成闭环毛线团的会籍匹配图。

## What Changes

- 从所有 ACTIVE StatusMatch watch 的当前 FactSet 构建只读有向图，边方向固定为“当前持有的来源会籍 → 可以申请的目标会籍”。
- 将项目名与等级规范化为稳定节点，同时保留原文标签、活动、条件、冲突及证据，不使用新的关系 AI。
- `AVAILABLE` 和 `CONDITIONAL` 生成可遍历边；`UNAVAILABLE` 仅保留为审计记录，不进入可达路径。
- 支持“所有/任意航司、酒店或会籍等级”通配映射：查询时展开到符合类别的已知具体节点；未明确来源等级时生成明确标记为 `UNCERTAIN` 的边，不能伪装成确定匹配。
- 提供以任一具体会籍为根的树状展开查询。沿当前路径回到祖先的边标记为 cycle 并截断；已从其他分支展开过的节点标记为 cross-reference 并停止重复递归。
- 为深度、节点数和每节点分支数设置上限，输出截断原因，使结果保持清晰可读。
- 提供机器可读的图快照、根节点树查询和审计报告，报告孤立边、歧义边、冲突边、潜在环和事实证据。
- 使用当前八个真实 StatusMatch 项目进行人工审核，核对边方向/等级是否忠于 FactSet，并判断树状展开是否清晰、无无限闭环。
- 本 change 不实现第三方文章附加关注点，也不让普通文章进入 StatusMatch 图。

## Capabilities

### New Capabilities

- `statusmatch-membership-graph`: 从当前 StatusMatch FactSet 构建证据可追溯的规范化有向匹配图，并提供有界、无无限递归的根节点树状查询与图逻辑审计。

### Modified Capabilities

无。

## Impact

- 新增独立的 `journeyplus.statusmatch.graph` 模块、严格图契约和 CLI 查询/审计入口。
- 读取现有 StatusMatch watch、event 和当前 FactSet，不新增模型调用，不修改第一阶段 FactSet 或简报。
- 不要求新数据库表；图由当前事实确定性重建，FactSet 更新后查询自动反映新映射。
- 增加规范化、通配展开、环/交叉引用截断以及真实数据审计测试。
