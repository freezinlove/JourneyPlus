## Context

JourneyPlus 当前是 Python/FastAPI/SQLAlchemy/PostgreSQL 应用，已有两条会籍事实来源：StatusMatch 官方项目快照和 LoyaltyLobby 普通文章。两类来源都能形成证据化 `FactSet`，其中直接会籍映射已经通过 provenance 合并到统一会籍图。统一图当前提供有深度、节点和分支上限的单根嵌套树以及完整管理员审计；产品尚无用户持有会籍、公开产品 API 或用户页面。

当前 `ApplicationRoute` 已经把资格、地区、费用和入口绑定到同一作用域，但费用仍是自由文本。普通文章机会范围也包含精英定级进度、信用卡等广义会籍活动，不能直接作为个性化会籍匹配输入。现有 Brief 已经版本化生成并保存，产品收敛不得改变任何机会的简报生成范围。

项目没有前端构建工具、模板引擎或远程部署配置。本变更需要在不引入新应用栈的前提下交付四个可用页面。

## Goals / Non-Goals

**Goals:**

- 用二值 `OpportunityKind` 将个性化匹配输入与其他简报机会分开，同时保持全部现有简报照常生成和展示。
- 为路线保存有证据的目标等级、原币金额和可用性，并对旧数据提供保守兼容。
- 保存单个本地用户的已有会籍，并严格从统一图规范化目录选择。
- 从多个会籍根构建无固定业务深度的可达子图，保留循环边、多条入边和交叉引用。
- 在匹配页面将完整可达响应投影为多源最短路径树，每个会籍只显示一次且不绘制循环和额外入边。
- 通过 provenance 将映射边还原为当前活动、路线、价格、条件、期限、简报和证据。
- 默认生成中国地区提示，但不据此过滤、排序、阻止或替换价格。
- 在现有 FastAPI 进程内提供 JSON API 和四个轻量用户页面。
- 保持用户查询零 AI 调用，并让买分来源退出每日自动选择。

**Non-Goals:**

- TravelerProfile、SavedMatchPath、ChallengeRule、账号和多用户隔离。
- 直接匹配/条件匹配/公开挑战的额外业务分类或页面分区。
- 业务路径深度上限、枚举并持久化所有简单路径或保存传递边。
- 自动汇率换算、按地区自动选最低价、地区资格裁决或绕过建议。
- 收藏、申请进度、提醒、自动报名、旅行计划、权益估值、多 Agent 和聊天式推荐。
- 新的 JavaScript 框架、Node 构建链或独立前端部署。

## Decisions

### 1. 事实 JSON 扩展，只有 StatusHolding 新建业务表

`OpportunityKind` 和 `RoutePrice` 属于当前机会事实快照的一部分，加入 Pydantic `FactSet`、普通文章提取契约和 StatusMatch 项目提取契约，继续存放在已有 `facts` JSON 中。只为 `StatusHolding` 新建关系表。

这样可以继续使用现有 FactSet/ArticleOpportunity 版本、签名、证据和 Brief 输入边界，避免再建一套 Opportunity 投影表。备选方案是为类型、地区和每个价格建立规范化关系表；该方案会增加同步、版本和来源追溯复杂度，因此不采用。

### 2. OpportunityKind 只控制个性化匹配，不控制简报

枚举只包含 `STATUS_MATCH` 和 `OTHER`。StatusMatch 官方项目在服务端确定性写为 `STATUS_MATCH`；普通文章在现有正文理解调用中输出类型。提示词把直接匹配、会籍挑战、Fast Track 和临时会籍挑战归入 `STATUS_MATCH`，把信用卡赠送会籍、定级进度促销和其他非匹配活动归入 `OTHER`。

所有机会无论类型都继续进入现有 Brief 生成、保存和简报页。只有统一会籍贡献和个性化机会集合读取 `OpportunityKind`。这使类型字段成为产品投影边界，而不是内容发布边界。

旧 JSON 缺少字段时使用保守兼容函数：官方 StatusMatch provenance 视为 `STATUS_MATCH`；普通文章优先读取显式字段，缺失时只对有直接会籍映射或明确目标会籍与挑战要求、且不含信用卡/定级进度信号的历史记录推断为 `STATUS_MATCH`。迁移会把当前数据写入显式值，运行时兼容保留给旧备份和测试夹具。

### 3. 路线价格既保存结构化值，也永远保留原文

`ApplicationRoute` 增加 `prices: list[RoutePrice]`。每个价格包含可空目标等级、可空金额和币种、可用性、原始文本和证据。路线内的共同申请费、复杂升级费或无法可靠合计的价格允许只保存 `raw_text`，不得为了填金额进行推算。

新材料在现有事实提取调用中输出 `prices`；HTML 表格或稳定格式优先使用确定性解析。旧材料和模型漏填时，读取层使用保守价格解析器处理常见 `Tier: CUR amount`、`CUR amount` 和 unavailable 文本，并在无法可靠拆分时回退到原始 `cost`。全局 FactSet 费用对全部路线共同适用时，读取层可以作为每条路线的只读继承价格，但不覆盖路线自己的价格。

备选方案是在用户打开详情时调用模型拆价；该方案会产生不稳定结果和交互成本，违反零 AI 查询目标，因此不采用。

### 4. StatusHolding 直接引用规范化项目和等级键

新表保存 `program_key`、`tier_key` 和稳定显示名，可选 `valid_until`，并以 `program_key` 唯一约束保证单用户同项目只有一个当前会籍。创建和更新必须由统一图目录解析到现有节点，不能把无法识别的自由文本写入数据库。

不保存 user_id。未来若真的建设多用户，单独迁移增加所有权；第一版不提前建设账号抽象。

### 5. 个性化响应是多根可达子图，不是所有简单路径列表

统一图服务新增目录和多根 reachability 读取。遍历从所有 StatusHolding 节点开始，沿直接边和适用通配规则持续展开，不设置业务深度上限。

算法维护：

- 当前递归祖先集合：目标已在祖先中时保留边、标记 `CYCLE` 并停止该分支；
- 全局已展开集合：目标已经在其他分支或根完整展开时保留边、标记 `CROSS_REFERENCE`，不重复复制子图；
- 技术节点预算：只防止意外超大响应，达到时返回明确的 `NODE_LIMIT` 和 continuation 信息，不作为会籍路径深度规则。

同一节点的所有入边保留，但后续子图只展开一次。系统不持久化 A→C 传递边，也不枚举可能呈指数增长的所有简单路径。

### 6. 机会由 contribution provenance 还原

个性化边保留其 contribution IDs，并将每个 contribution 的 `fact_set_id/event_id` 或 `opportunity_id` 解析为稳定的产品机会 ID。详情服务读取当前 StatusEvent/FactSet/Brief 或 ArticleOpportunity/ArticleBrief，返回统一详情契约。

普通文章贡献适配器只把 `STATUS_MATCH` 的当前、可见、有证据映射加入统一图。没有 status_mappings 但显式属于 `STATUS_MATCH` 的当前文章机会作为 `path = null` 的独立结果加入同一个匹配响应，不建立额外分类。

### 7. 中国地区提示是只读派生值

应用常量为 `CN/中国`。读取层只在条款明确包含中国/全球、明确排除中国时生成 INCLUDED/EXCLUDED；其他情况为 NOT_EXPLICIT 并展示原始文本。提示不进入图过滤、排序、价格选择或写入数据库。

### 8. 产品 UI 使用同源 FastAPI 和原生静态资源

新增独立 `create_product_app`，提供 `/v1` API 和四个 HTML 路由。页面使用一个共享 HTML shell、包内 CSS 和原生 JavaScript，通过同源 API 获取数据：

- `/holdings`：我的会籍；
- `/matches`：个性化匹配图；
- `/briefs`：全部现有简报；
- `/opportunities/{id}`：机会详情。

CLI 增加本地产品服务入口。内部审核 API 保持独立，避免公开页面带出审核写接口。没有 Node、模板引擎或 CDN 依赖。

匹配页不会直接把后端嵌套响应中的循环和交叉引用 occurrence 全部画成卡片。前端先汇总唯一节点和直接边，再从全部 holding 根执行稳定的多源广度优先遍历；节点首次到达时确定其最小跳数和唯一父边，后续到达边及回边不进入画布。由此每个会籍只出现一次，画布是一棵或多棵无环最近路径树，而后端完整 provenance 和可达关系保持不变。

### 9. 简报页统一读取全部当前简报

简报读取服务合并当前官方 BriefRecord 和当前普通 ArticleBriefRecord，返回统一列表项。`OpportunityKind` 只作为可显示元数据，绝不作为默认过滤或生成条件。存在映射时返回匹配图/详情链接；否则仍展示现有 Brief 和来源。

### 10. 买分只退出自动选择

来源注册表把 AwardWallet 买分页的 `automatic_scheduling` 设为 false；代码、数据库、CLI 和手工运行能力不删除。已有数据库通过 seed 或迁移同步关闭自动调度。

## Risks / Trade-offs

- [旧价格文本格式多样，无法全部数值化] → 永远保留 raw cost；只有证据充分时返回 amount/currency，并为真实地区价格案例增加回归测试。
- [无深度上限的图可能很大] → 返回去重可达子图而非所有路径，使用跨分支引用和明确技术节点预算；前端按需展开。
- [历史 OpportunityKind 推断可能误分] → 官方确定性，普通历史保守推断并显式回填；简报完全不受类型影响，误分只影响个性化图且可审核修正。
- [多根遍历顺序影响哪个节点首次展开] → 根和边按规范键稳定排序，响应在相同数据库快照下确定性一致。
- [单用户表阻碍未来多用户] → 这是明确产品边界；未来真实需要出现时增加所有权迁移，不提前支付复杂度。
- [原生 JavaScript 的组件能力有限] → 页面仅承担 CRUD、树展开、筛选和详情读取；不引入超出第一版范围的复杂交互。

## Migration Plan

1. 新增 Alembic 迁移创建 `status_holdings`，为当前 JSON 事实保守回填 `opportunity_kind` 和可确定的路线价格，并关闭买分来源自动调度。
2. 部署兼容旧 JSON 的 Pydantic 契约和读取逻辑；旧备份即使没有新字段仍可读取。
3. 更新现有提取 Schema/Prompt 版本，使新材料直接生成类型和路线价格；StatusMatch 项目由服务端注入类型。
4. 部署个性化服务、API 和页面；先用 SQLite 集成测试，再对本地 PostgreSQL 执行 `alembic upgrade head`。
5. 运行当前数据审计，确认 holdings 为空、简报数量未减少、统一图只移除显式 OTHER 普通贡献、地区价格代表案例可读。

回滚时先停止产品服务，再降级迁移删除 `status_holdings` 并恢复买分自动调度字段。JSON 中新增字段是向后兼容数据；downgrade 可以移除新键，但不得删除原始 cost、事实、Brief 或来源数据。

## Open Questions

无。产品边界、默认地区、遍历行为、简报范围和页面数量已经由总方针确定。
