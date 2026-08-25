## ADDED Requirements

### Requirement: 统一树只消费边界明确的当前直接映射
系统 SHALL 通过来源中立的贡献契约读取 StatusMatch ACTIVE 项目当前官方 FactSet 的直接映射和未路由到 StatusMatch 的普通第三方 ArticleOpportunity 当前直接映射，且 SHALL 防御性排除任何存在 StatusMatchArticleRoute 的文章版本。

#### Scenario: 只有 StatusMatch 官方映射
- **WHEN** 当前有效数据只有一条 StatusMatch 官方直接映射
- **THEN** 统一树包含该直接边
- **AND** 现有官方 FactSet、Brief 和官方图输入不被修改

#### Scenario: 只有普通第三方映射
- **WHEN** 最新成功的普通 ArticleOpportunity 含有一条证据有效且当前可见的直接映射
- **THEN** 统一树包含该直接边
- **AND** 系统不要求该文章绑定 StatusMatch 项目或共享事件

#### Scenario: StatusMatch 关联文章含有会籍描述
- **WHEN** 一个第三方文章因精确 `*.statusmatch.com` 链接进入 StatusMatch 补充分支
- **THEN** 该文章不得通过任一适配器向统一树贡献直接边

### Requirement: 普通文章映射必须可遍历且有文章证据
普通文章贡献适配器 SHALL 只发布成功分析中逐字证据校验通过、`conflict=false` 且 availability 为 AVAILABLE 或 CONDITIONAL 的具体直接映射；UNAVAILABLE、冲突、拒绝、无源等级或无证据声明 SHALL 只可保留用于审计而不得成为用户可遍历边。

#### Scenario: 条件映射有效
- **WHEN** 普通文章明确给出原项目、原等级、目标项目、目标等级、条件和可定位证据
- **THEN** 统一树包含一条 CONDITIONAL 直接边并保留条件语义

#### Scenario: 文章自身映射冲突
- **WHEN** ArticleOpportunity 的映射标记为 conflict 或证据校验失败
- **THEN** 默认统一树不包含该贡献
- **AND** 管理审计可以定位被排除原因和原文章证据

#### Scenario: 不可用映射
- **WHEN** 普通文章明确说明某项匹配不可用
- **THEN** 该声明不得成为可遍历边

### Requirement: 同一直接边确定性聚合且默认不区分来源
系统 SHALL 以规范化后的起点会员节点和终点会员节点作为边身份，将相同节点对的所有当前有效贡献聚合为一条用户边，并在内部保留每个贡献者、证据、条件、有效期和来源身份；默认用户树 SHALL 不返回官方/第三方徽标、来源等级或贡献者列表。

#### Scenario: 官方与文章贡献相同边
- **WHEN** StatusMatch 官方 FactSet 和一篇普通文章都支持同一规范化 `A 等级 → B 等级`
- **THEN** 用户树只展示一条 `A → B` 边
- **AND** 管理审计显示两个独立贡献及各自证据

#### Scenario: 相同边具有条件变体
- **WHEN** 同一规范化节点对的有效贡献具有不同的明确条件
- **THEN** 用户树仍只有一条边并以来源中立方式返回去重后的条件变体
- **AND** 内部贡献不得被事实合并或覆盖

#### Scenario: 用户与管理员读取
- **WHEN** 普通用户和管理员查询同一棵树
- **THEN** 两者获得相同拓扑
- **AND** 只有管理员审计合同包含来源、文章、FactSet 和贡献者溯源

### Requirement: 混合来源直接边可形成有界多跳树
统一树 SHALL 逐层遍历当前聚合的直接边，允许相邻层来自不同适配器，并 SHALL 沿用循环、交叉引用、深度、节点和分支限制；系统不得生成或持久化原始贡献中不存在的传递边。

#### Scenario: 官方后接普通文章
- **WHEN** 官方贡献为 `A → B` 且普通文章贡献为 `B → C`
- **THEN** 以 A 为根的树展示 `A → B → C`
- **AND** 系统不得保存或展示一条直接 `A → C`

#### Scenario: 普通文章后接官方
- **WHEN** 普通文章贡献为 `A → B` 且官方贡献为 `B → C`
- **THEN** 以 A 为根的树展示 `A → B → C`

#### Scenario: 混合来源形成循环
- **WHEN** 当前直接贡献形成 `A → B → C → A`
- **THEN** 回到 A 的关系以 CYCLE 叶子结束
- **AND** 查询在配置限制内完成

#### Scenario: 共享节点和查询限制
- **WHEN** 多个分支到达同一已展开节点或达到深度、节点、分支限制
- **THEN** 树返回 CROSS_REFERENCE 或准确的截断原因和遗漏数量

### Requirement: 统一读取层与来源工作流低耦合
`UnifiedMembershipTreeService` SHALL 只依赖来源中立的贡献适配器和确定性图组件；StatusMatch 官方工作流与通用文章工作流 SHALL 不互相调用，统一树构建 SHALL 不修改业务记录或调用 AI、候选召回、关系分析及跨文章聚合。

#### Scenario: 架构依赖检查
- **WHEN** 检查统一树、StatusMatch 和普通文章模块依赖
- **THEN** StatusMatch 官方工作流不导入普通文章处理服务
- **AND** 普通文章工作流不导入 StatusMatch 项目处理服务
- **AND** 只有统一读取层组合两个适配器

#### Scenario: 完全相同输入重建统一树
- **WHEN** 当前 FactSet、ArticleOpportunity 和可见期均未变化并再次查询或审计
- **THEN** 输出确定性一致
- **AND** 新增模型调用数为零

### Requirement: 官方审计图保持权威且用户入口使用统一树
现有 `MembershipGraphService` SHALL 继续只从 StatusMatch 官方当前 FactSet 构建官方审计图；面向用户的树 CLI/API SHALL 使用统一树服务，而管理员 SHALL 能分别审计官方事实忠实度与统一贡献拓扑。

#### Scenario: 仅官方投影回归
- **WHEN** 暂时禁用普通文章贡献并用相同根节点查询两种服务
- **THEN** 统一树的节点、直接边和有界遍历拓扑与官方树等价

#### Scenario: 普通文章加入后
- **WHEN** 一条有效普通文章贡献加入统一树
- **THEN** 用户树可展示该边
- **AND** 官方审计图的 expected claims、边、规则和 FactSet 列表保持不变

