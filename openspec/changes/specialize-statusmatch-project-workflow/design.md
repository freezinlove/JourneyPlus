## Context

JourneyPlus 已具备持久化 StatusMatch watch、每个项目一个首页加一个 FAQ、页面版本哈希、确定性整体关闭判定以及双页当前快照。当前语义处理仍复用普通文章的逐文档 `V1Workflow`：首页先分类、建活动、整理事实和生成简报，FAQ 随后再次分类、关系判断、整理事实和生成简报。真实数据库显示首次项目通常调用六次模型，部分项目还因无关候选或同项目 FAQ 触发关系 AI。

StatusMatch 项目拥有比普通文章更强的确定性边界：受管项目 host 唯一标识一个当前 watch；一个 watch 的首页和 FAQ 属于同一现实活动；不同 host 不合并；watch 归档后重新建立代表新一期。页面事实以当前双页快照为准，Gmail 只负责发现。

后续路线分三阶段：本 change 实施第一阶段专用链路；第二阶段会籍匹配图消费标准化映射；第三阶段第三方文章通过精确项目链接成为 StatusMatch 项目的补充关注点。后两阶段不得反向要求第一阶段复用通用文章关系判断。

## Goals / Non-Goals

**Goals:**

- 以一个 active watch 的当前首页和 FAQ 作为原子语义输入。
- 取消受管 StatusMatch 页面分类 AI、候选召回和关系 AI。
- 首次及每次语义更新最多执行一次项目事实 AI 和一次必要的简报 AI。
- 由一次项目事实输出同时建立项目身份和完整 FactSet。
- 使用页面别名表达 AI 证据，并由服务层绑定真实文档 ID 与 URL。
- 合并确定性 HTML 表格映射与 AI 从非表格正文提取的映射。
- 对完整新旧 FactSet 做确定性结构化差异，记录用户可审计的 ChangeSet。
- 事实签名未变化时复用原 FactSet 和简报。
- 保证受管页面不会再进入通用逐文档工作流。
- 对真实公开页面进行端到端和人工内容审计。

**Non-Goals:**

- 本 change 不实现跨项目会籍匹配图、项目/等级别名注册表或 wildcard 图展开。
- 本 change 不接入 LoyaltyLobby 等第三方文章，不生成第三方补充关注点。
- StatusMatch 不与普通文章事件合并，即使普通文章报道同一活动。
- 本 change 不让 AI 输出增量补丁；项目事实仍为完整当前快照。
- 本 change 不改变普通文章分类、候选和关系工作流的行为；通用关系 AI 上下文缩减另行实施。

## Decisions

### 1. 新增项目级 `StatusMatchProjectWorkflow`

专用工作流由 watch 驱动而不是 DocumentVersion 驱动。只有同时存在无错误的当前 activity 与 FAQ 文档且关闭判定为 active 时才可处理。项目级幂等键包含 watch ID、两个当前文档 ID、模型配置、项目 prompt/schema 版本和简报版本。

自动化顺序为：监控已有 watch、采集新 Gmail host、处理所有待处理 StatusMatch 项目、处理普通文档、推进生命周期。这样首次 Gmail 接入与页面更新都进入同一项目处理入口。

替代方案是继续让首页和 FAQ 分别进入 V1Workflow 并增加等待逻辑，但该方案仍保留不必要的分类和关系抽象，难以保证只生成一次事实和简报。

### 2. watch 是当前 StatusMatch 活动的确定性关系边界

新 watch 首次处理时创建一个占位事件，稳定键为 `statusmatch-watch:{watch.id}`；项目 AI 成功后以结构化 identity 更新 program、target_status、summary 和 search_text。同一 watch 后续永远更新 `current_event_id`。不同 host 不召回、不比较、不合并。watch 删除后新建会获得新 ID，因此同一 host 的新一期不会与归档活动合并。

这取代所有 StatusMatch 关系 AI。普通文章仍使用现有通用关系链路。

### 3. 项目 AI 输出 identity 与别名证据事实

模型输入包含项目 host、`HOME` 和 `FAQ` 当前完整规范化正文、各自 URL、当前 FactSet（更新时）、确定性映射计数/键以及明确的 active/ended 规则。模型输出一个严格结构：

- `identity`: program、summary、target_status；
- 完整事实字段；
- application routes；
- 仅来自非表格正文的 narrative status mappings；
- 每条证据只引用 `HOME` 或 `FAQ` 及短 locator。

服务层把别名解析成真实 `EvidenceRef`，注入当前事件 ID，校验引用范围，规范化项目首页 action link，合并确定性表格映射并执行现有地域、冲突和生命周期守卫。

替代方案是让模型继续复制 UUID 和 URL，但这会增加输出 token、格式错误和伪造标识风险。另一个替代方案是先调用 identity AI 再调用 FactSet AI，会重新增加一次模型调用。

### 4. 完整快照重建并由程序计算变化

每个新双页组合都让模型输出完整当前事实，不使用 AI delta。完整快照可以明确表达字段删除，避免“未输出”究竟代表删除还是遗漏的歧义。

服务层比较不含证据定位的 material signature：

- 相同则复用当前 FactSet 与 Brief，并记录页面变化但语义不变；
- 不同则创建新 FactSet，并按字段、申请路径和映射稳定键生成 ChangeSet；
- 初次快照记录 `INITIAL_SNAPSHOT`。

ChangeSet 与 event、前后 FactSet、当前双页文档绑定。旧 FactSet、Brief 和文档继续保留。

### 5. 映射采用表格与正文双通道

现有 HTML 解析器继续产生确定性表格映射。项目 AI 不复制表格内容，只输出表格外正文明确支持的映射；服务层按规范化 source program、source tiers、target tier、availability 和 conditions 合并去重并保留证据。

任意航司、未明确等级和图结构的扩展留给第二阶段 capability；本阶段保证正文映射不会因为页面同时存在确定性表格而被整体丢弃，并保留可扩展的结构化来源。

### 6. 通用工作流在选择阶段排除受管页面

`status_services_mail` 中 external ID 以 `statusmatch-page:` 开头的文档不再进入通用 pending document 选择。Gmail 邮件文档仍可被现有确定性 discovery-only 分类记录处理。该过滤基于 source/external identity，不依赖数据库 JSON 方言。

### 7. 简报复用现有生成与校验能力

专用事实服务生成或复用 FactSetRecord 后继续调用现有 BriefGenerator。首次只有一个 FactSet，因此只生成一份简报；更新事实签名相同时传回同一 FactSetRecord，BriefGenerator 幂等复用，不调用模型。

### 8. 分阶段接口边界

第二阶段匹配图在独立模块消费当前 FactSet 的标准化 mappings；映射提取留在 StatusMatch 写入链路，图查询、wildcard 展开和 UI 独立。第三阶段第三方文章以精确 host 建立附件并在官方简报完成后生成补充关注点；它不得进入本专用项目的分类或关系判断。

## Risks / Trade-offs

- [项目 AI 一次输出 identity 和大量事实，schema 较大] → 保留两次有限重试、严格 Pydantic 校验、证据别名和纠错上下文，并用真实长 FAQ 验证。
- [创建占位事件后 AI 失败] → 项目任务在单一事务中运行，失败回滚占位事件和关联；JobRun 记录失败供重试。
- [正文映射与表格映射重复或冲突] → 使用稳定映射键去重；不同语义保留冲突标记和双方证据。
- [排除通用页面导致旧 pending JobRun 残留] → pending 选择立即排除受管页面；历史 AnalysisRun 和 JobRun 保留作审计。
- [真实页面长文本导致 token 增长] → 首次只调用一次事实模型；移除重复 UUID/URL；后续可在不改变输出契约的前提下增加语义区块压缩。
- [模型每次改写措辞造成虚假 FactSet 变化] → material signature 忽略证据版本，但仍对事实文本敏感；测试要求同义稳定，人工审计真实输出，后续可增加字段级规范化。
- [本阶段映射 schema 尚不能完整表达 ANY_AIRLINE/UNCERTAIN 图边] → 第二阶段在不重新抓取页面的前提下扩展 canonical graph edge；本阶段保存原始正文证据与叙述映射。

## Migration Plan

1. 新增 ChangeSet 表和迁移，先备份并升级本地 PostgreSQL。
2. 部署项目 contracts、处理服务和通用 pending 排除规则。
3. 将自动化编排切换为项目处理优先、普通文档处理随后。
4. 在临时数据库用首页＋FAQ fixture 验证首次、更新、无变化、关闭和失败。
5. 对现有八个 watch 运行新的项目幂等任务；已有 event 继续使用，不创建重复活动。
6. 使用真实公开页面核对至少一个长表格项目和一个不同页面形态项目，人工审计模型输入摘要、调用次数、FactSet、mapping、ChangeSet 和 Brief。

回滚时恢复自动化旧编排并停止项目任务；新增 ChangeSet 表可由迁移 downgrade 删除。既有文档、事件、事实和简报不删除。由于通用页面历史仍保留，回滚后旧工作流仍可重新处理最新文档。

## Open Questions

无阻塞问题。ANY_AIRLINE/UNCERTAIN 图边和第三方简报补充点分别由后续 OpenSpec change 定义。
