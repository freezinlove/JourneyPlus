## Context

第一阶段已经把每个受管 `*.statusmatch.com` host 固定为一个 watch，以 HOME+FAQ 当前快照生成官方 FactSet 和官方 Brief；第二阶段只读这些标准化事实构建会籍匹配图。普通来源文章仍按文档进入通用 `V1Workflow`，会执行分类、候选召回、关系判断、事实合并和简报生成。

第三方报道的占比很低，但其正文可能同时包含一个具体 StatusMatch 项目链接和官网没有强调的实用观察。项目边界在这种情况下已经由链接确定：文章不应再被分类、召回或合并成另一个活动；同时第三方观点也不应写回官网 FactSet，造成来源层级混杂。LoyaltyLobby 只允许使用 Feed 提供的正文进行机器处理，真实文章页仅用于人工可见核验。

## Goals / Non-Goals

**Goals:**

- 只以正文中的具体、可规范化 `*.statusmatch.com` 项目链接触发第三方专用路径。
- 对缺失项目先完成 HOME+FAQ 接入和官方项目处理；已有项目不因文章出现而刷新官网。
- 以 host 确定性关联当前 event，不调用分类 AI、候选召回或关系 AI。
- 一次 AI 比较文章与当前官方 FactSet+Brief，只输出由文章原文支持且官方内容未覆盖的关注点。
- 分开保存官方 Brief 与第三方补充，在读取时组合，并保留文章、文档版本、官方 FactSet 和证据摘录。
- 保证普通无链接文章、Gmail 发现邮件、官网页面和会籍匹配图行为不变。
- 在每日自动化、初始化和专用验收入口中保持可恢复、可幂等和可计量。

**Non-Goals:**

- 不把没有精确 StatusMatch 项目链接的“疑似相关”文章交给 AI 猜测项目。
- 不把第三方文章事实写入官方 FactSet、官方 Brief、StatusMatch mapping 或匹配图。
- 不把文章创建成独立事件，也不做跨 host 关系推断。
- 不抓取 LoyaltyLobby 文章页作为机器正文；文章页只用于人工验收，机器正文继续来自 Feed。
- 不让模型改写整份官方简报；组合读取面负责附加补充关注点。

## Decisions

### 1. 路由是一个窄的确定性前置分支

复用现有 `extract_statusmatch_project_links` 读取第三方文档的原始 HTML；只有非 `status_services_mail`、非 `statusmatch-page:` 受管页面且至少含一个具体项目链接的文档才是第三方附件。每个 `(document_version_id, project_host)` 建立一条持久化 route。

通用 pending 选择在同一判定函数上排除这类文档。无有效链接的文章仍原样进入 `V1Workflow`；Gmail 继续只做发现；受管 HOME/FAQ 继续只进入官方项目链路。共同使用一个判定函数避免“附件扫描认为命中、通用流程却也处理”的双路分叉。

替代方案是在通用分类 AI 后识别 StatusMatch，但这会给绝大多数文章增加输出契约，并仍可能先创建重复事件。

### 2. route 先持久化，再按项目准备状态推进

`statusmatch_article_routes` 保存文章文档、host、规范 URL、确定性关联状态、当前 event 和错误。首次发现未知 host 时建立 watch；只抓取新建或尚无完整双页快照的 watch，不刷新已有 ACTIVE watch。抓取关闭页时 route 标记为 `OFFICIAL_CLOSED`，避免同一旧文章每天重新创建并抓取已结束项目。

自动化顺序变为：监控既有 watch、采集来源、发现并准备第三方 route、处理相关官方项目、处理第三方补充、处理普通文档、推进生命周期。初始化对本批文档执行相同局部顺序。官网抓取或项目 AI 暂时失败时 route 保持等待/失败态，后续可重试，且不会退回通用链路。

### 3. host 是唯一关系依据

route 只有在对应 ACTIVE watch 已有未归档 `current_event_id`、当前 FactSet 和当前 Brief 时才能生成补充。关联直接写入该 event，不执行状态分类、候选召回或关系 AI。文章含多个有效 host 时建立多条 route，分别与各自官方材料比较；不同 host 之间不产生关系。

watch 后续归档不删除历史 route 和 supplement。新文章再次发现同一已结束 host 时仍按当前页面重新接入，若官网确有新一期则形成新的 watch/event；旧文章 route 不自动迁移到新一期。

### 4. 官方记录与第三方补充分层持久化

官方 `FactSetRecord`、`BriefRecord` 和匹配图输入不变。`statusmatch_article_supplements` 以 route、event、文章文档版本、用于比较的官方 FactSet/Brief 和输入版本保存一次结果；结果可以是若干关注点，也可以是明确的 `NO_NOVEL_HIGHLIGHTS`。

每个关注点保存简洁中文表述、文章原文短摘录和“相对官网为何是新增”的说明。服务端验证原文摘录确实出现在该文章规范正文中，并把真实 document ID、URL 和时间信息从数据库绑定进去，不允许模型输出或伪造这些标识。

项目读取服务返回官方 Brief 原文和当前有效的第三方补充数组，不把补充物理写回官方 Brief。这样官网更新可以继续独立复用/重建，第三方来源也可单独审计、撤下或重新比较。

### 5. 每个 route/官方版本最多一次补充 AI

补充 prompt 输入固定为：`ARTICLE` 标题、URL、规范正文；当前官方 FactSet；当前官方 Brief；确定的 project host。模型不再分类、不输出关系、不重述官网，只输出官网两份材料均未覆盖、对理解或申请有实际价值且 ARTICLE 明确支持的内容。

项目幂等键包含 route、文章文档、当前 FactSet、当前 Brief、provider config、prompt/schema 版本。相同输入复用既有成功结果；官网 FactSet/Brief 变化时生成一个新 supplement 版本并由组合读取面只选择与当前官方版本匹配的结果。空数组也是成功结果，避免无新增信息的文章重复调用。

### 6. 证据与“未覆盖”采用双重守卫

结构契约要求每个关注点提供短原文摘录和 novelty reason。程序对空值、数量、重复和摘录存在性做确定性校验；失败时把纠错信息带入一次有限重试。语义上的“官网是否已经覆盖”由同一次模型比较完成，真实验收再人工对照 ARTICLE、HOME、FAQ、FactSet 和 Brief。

不采用纯字符串 diff：第三方文章与官网措辞、语言和结构不同，字符串差异会把同一事实大量误报成新增。也不让模型直接输出整份改写简报，因为这会掩盖来源边界并增加重复内容。

### 7. 组合简报和审计是只读消费面

StatusMatch 项目组合简报按 host/event 返回官方内容、当前补充、等待/失败 route 及完整来源元数据。CLI 和内部 review API 复用同一服务。验收命令另外报告：是否命中专用路由、通用工作流是否产生分类/关系运行、官网是否被不必要刷新、模型调用数、补充证据是否可在正文定位。

第二阶段会籍图继续只读官方当前 FactSet，因此第三方补充不会新增边、修改方向或制造环。

## Risks / Trade-offs

- [文章链接在脚本、导航或引用区而非报道对象中] → 只接受具体项目 host，并保留链接标签与文章 route 供审计；一文多 host 分开处理，不由 AI 猜主次。
- [Feed 规范正文丢失 href] → 路由优先解析保存的原始 Feed HTML，规范正文只作后备；测试覆盖 HTML anchor 和纯文本 URL。
- [新 host 的官网抓取失败] → route 保持等待/错误并保留 watch，下一周期先由常规监控恢复；不误入通用流程。
- [活动初次发现时已经关闭] → 确定性关闭规则归档/移除 watch，并将对应旧 route 标记 `OFFICIAL_CLOSED`，避免无限重抓。
- [模型把官网已有事实换句话说成新增] → 同时注入结构化 FactSet 和最终 Brief，要求 novelty reason；真实文章验收逐条人工核对，后续可增加人工否决状态而无需污染官方记录。
- [文章原文摘录因空白或 HTML 实体不完全一致] → 用与正文抽取一致的 Unicode/空白规范化做包含校验，仍不匹配则有限重试并失败待查。
- [官方更新后旧补充不再新增] → 以当前 FactSet/Brief 重新比较并只展示当前 supplement；历史版本保留审计。
- [新分支侵占普通文档预算] → 只对精确链接命中的极少数文章调用一次 AI，汇总分别计数；普通文章的选择和预算规则不扩张。

## Migration Plan

1. 新增 route 与 supplement 模型和 Alembic 迁移，不回填或修改官方事实。
2. 增加统一第三方命中判定、发现/官网准备、补充工作流和组合读取服务。
3. 在通用 pending 选择接入同一排除判定，并调整每日自动化、初始化、CLI 与 review API 编排。
4. 用 fixture 覆盖未知/已有/关闭 host、一文多 host、零新增、幂等、官网更新、失败重试和普通文章不受影响。
5. 在本地数据库使用 LoyaltyLobby Kenya Airways / Accor Feed 正文，真实抓取链接的 StatusMatch HOME+FAQ，运行端到端验收；再用可见浏览器人工对照原始文章页和官网页面。

回滚时先停用第三方分支并恢复通用 pending 排除前行为，再 downgrade 删除两张新增表。官方 StatusMatch 数据、普通事件和匹配图无需回滚。已被第三方分支排除但尚未处理的普通文档在回滚后会重新出现在通用 pending 队列。

## Open Questions

无阻塞问题。第三方关注点将来是否允许人工置顶、隐藏或编辑属于后续 review/UI change；本阶段保留足够的 route、版本和证据标识支持该能力。
