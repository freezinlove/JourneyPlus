## ADDED Requirements

### Requirement: Retain model-generated Chinese briefs
简报 SHALL 保留原有模型编辑、内容组织、更新摘要、缓存与重试能力，输入为统一版本结构化事实，保存到 activity_briefs。MUST NOT 用现有简化投影替代原模型简报，或独立推断费用与资格。

#### Scenario: A new knowledge draft is ready for briefing
- **WHEN** 原提取阶段形成已校验的活动和方案事实
- **THEN** 原简报阶段通过调整后的输入契约生成中文简报，绑定该知识版本；打开页面不再临时调用模型

### Requirement: Keep linked article highlights separate from formal facts
关联 StatusMatch 文章 SHALL 按原流程读取官方结果并提取亮点，保存为版本关联补充，保留文章标题、原文链接和时间。它 MUST NOT 覆盖官方事实或贡献普通文章匹配边。

#### Scenario: The article has no new highlights
- **WHEN** 对照当前官方结果后没有新亮点
- **THEN** 记录成功且可复用的零亮点结果，不制造匹配边，不在每次调度重复调用模型

#### Scenario: One article links multiple projects
- **WHEN** 文章路由到多个 StatusMatch 项目
- **THEN** 按原文章/项目关系独立处理，保留历史期次关联，不把旧补充自动移动到新的活动期次

### Requirement: Use one deterministic knowledge graph semantics
完整图和 Agent 路径查询 SHALL 共用当前版本的映射、方案、条件和价格判断；图为确定性投影，不保存可独立修改的费用/资格真值，不调用模型。完整图 SHALL 保留原有多来源去重、多跳、循环和覆盖语义。

#### Scenario: Official and ordinary article mappings form a mixed path
- **WHEN** 已发布官方与普通文章映射共同组成多跳路径
- **THEN** 图和路径服务对同一输入版本得到一致的资格与费用判断，保留每步方案归属

#### Scenario: Several sources contribute the same edge
- **WHEN** 同一条边的一个贡献过期而另一个仍有效
- **THEN** 按原贡献合并语义保留有效边，不因单一来源过期删除全部贡献

### Requirement: Preserve article visibility independently of application deadlines
普通文章的默认 180 天图可见期、明确期限优先、缺发布时间回退、手工维护和最新成功版本语义 SHALL 保留；MUST NOT 将图可见期写成虚构的申请截止时间。

#### Scenario: No explicit deadline is extracted
- **WHEN** 普通文章没有明确申请期限
- **THEN** 按原政策计算图可见期，申请期限仍为未知；新文档重处理不得无故重置原可见窗口

### Requirement: Report graph coverage and version honestly
完整图 SHALL 使用明确的知识快照，区分完整结果、分页及技术预算截断。简报、详情、图与链接 SHALL 保持版本一致；关联引用不是逐条原文证据义务。

#### Scenario: Graph traversal reaches a technical budget
- **WHEN** 全图遍历触及状态、边数或时间预算
- **THEN** 明确返回范围与未完成状态，不以默认短名单冒充完整图或全量无结果

#### Scenario: Knowledge is updated after a user opens a brief
- **WHEN** 用户持有历史知识版本引用而当前版本已经变化
- **THEN** 仍能按原版本理解正式事实与对应文档，不静默替换为当前版本的费用或资格
