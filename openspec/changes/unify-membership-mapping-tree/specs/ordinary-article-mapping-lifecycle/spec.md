## ADDED Requirements

### Requirement: 普通文章映射可见期优先使用明确截止日期
每个普通 ArticleOpportunity SHALL 保存独立的内部 `visibility_until_at` 和 `visibility_policy`；当文章有可靠的明确申请截止时间时，系统 SHALL 使用该时间并标记 `EXPLICIT_DEADLINE`，不得同时套用默认 180 天上限。

#### Scenario: 明确截止日期早于 180 天
- **WHEN** 文章发布时间为 2026-08-24 且有证据的申请截止时间为 2026-09-30 日终
- **THEN** `visibility_until_at` 等于该申请截止时间
- **AND** 策略为 `EXPLICIT_DEADLINE`

#### Scenario: 明确截止日期晚于 180 天
- **WHEN** 文章给出的可靠申请截止时间晚于发布时间后 180 天
- **THEN** 系统仍使用文章明确截止时间
- **AND** 不以默认 180 天提前归档

### Requirement: 无明确截止日期时严格按 180 天计算
普通 ArticleOpportunity 没有可靠明确截止时间时 SHALL 以 `SourceItem.published_at + timedelta(days=180)` 计算可见截止；发布时间缺失时 SHALL 以不可变的 SourceItem 首次采集时间 `SourceItem.created_at + timedelta(days=180)` 计算，并标记 `DEFAULT_180_DAYS`，不得按自然月计算。

#### Scenario: 文章有发布时间但无截止日期
- **WHEN** 发布时间为 2026-08-24 10:00:00 且文章没有可靠截止日期
- **THEN** `visibility_until_at` 为 2027-02-20 10:00:00
- **AND** 策略为 `DEFAULT_180_DAYS`

#### Scenario: 文章没有发布时间
- **WHEN** 文章没有 published_at 且首次采集时间为 2026-08-25 03:00:00
- **THEN** `visibility_until_at` 为首次采集时间后恰好 180 天

#### Scenario: 同一文章产生新文档版本
- **WHEN** 同一 SourceItem 被重新抓取或重新解析为新 DocumentVersion
- **THEN** 新版本不得重置发布时间、首次采集时间或默认 180 天起点
- **AND** 默认树只消费该 SourceItem 最新成功分析版本的当前映射

### Requirement: 内部可见期不得伪装为业务截止日期
`visibility_until_at` SHALL 只控制普通文章映射贡献的新鲜度，不得写入 ArticleOpportunity FactSet 的 deadline、不得修改文章原始截止字段，也不得在默认用户简报中表述为活动官方截止日期。

#### Scenario: 无截止文章采用 180 天规则
- **WHEN** 系统为无截止文章计算内部可见期
- **THEN** 该 ArticleOpportunity 的 `deadline.value` 保持未知
- **AND** 已生成 Brief 不新增一个虚构的申请截止日期

#### Scenario: 管理员审计可见期
- **WHEN** 管理员检查该 ArticleOpportunity
- **THEN** 审计输出可以显示可见截止、计算策略和起算时间来源
- **AND** 明确标识它是内部 freshness 规则

### Requirement: 到期边界由读取和到期任务共同保证
普通文章映射 SHALL 仅在 `now < visibility_until_at`、未软归档且已到明确申请开始时间时可见；在 `now >= visibility_until_at` 时 SHALL 立即从统一树排除，并由确定性生命周期任务写入 `archived_at` 和相应归档原因。

#### Scenario: 默认 180 天第 179 天
- **WHEN** 当前时间仍早于 `visibility_until_at`
- **THEN** 其他发布条件均满足的映射贡献保持可见

#### Scenario: 默认 180 天精确边界
- **WHEN** 当前时间等于或晚于 `visibility_until_at`
- **THEN** 映射贡献不再出现在统一树
- **AND** 到期任务设置 `archive_reason=STALE_180D`

#### Scenario: 明确截止到期
- **WHEN** `EXPLICIT_DEADLINE` 机会达到或超过明确截止时间
- **THEN** 映射贡献不再出现
- **AND** 到期任务设置 `archive_reason=DEADLINE_EXPIRED`

#### Scenario: 到期任务延迟
- **WHEN** 当前时间已经到期但归档任务尚未运行
- **THEN** 统一树读取谓词仍排除该贡献

#### Scenario: 申请尚未开始
- **WHEN** ArticleOpportunity 有未来的可靠 application_start_at
- **THEN** 其映射在开始时间前不得成为当前可遍历边

### Requirement: 到期只软归档映射贡献
普通 ArticleOpportunity 到期时 SHALL 保留文章、DocumentVersion、ArticleAnalysis、ArticleOpportunity、FactSet、Brief、原文证据和历史版本，只通过软归档字段停止当前映射贡献。

#### Scenario: 无截止文章满 180 天
- **WHEN** 生命周期任务归档该 ArticleOpportunity
- **THEN** 文章事实和 Brief 仍可通过历史/管理读取访问
- **AND** 系统不删除任何源文档或证据

#### Scenario: 新文章重新报道活动
- **WHEN** 后续出现一个新的 SourceItem 并提取出相同直接映射
- **THEN** 新 ArticleOpportunity 独立计算自己的可见期并可以重新贡献该边
- **AND** 系统不需要判断两篇文章是否属于同一事件

### Requirement: 聚合边按有效贡献者存活
统一树 SHALL 针对每个直接边独立计算当前有效贡献者；一个贡献者到期或归档不得移除其他仍有效贡献者，只有最后一个有效贡献消失时该边才从当前树消失。

#### Scenario: 普通文章贡献到期但官方贡献仍有效
- **WHEN** 同一边的普通文章贡献到期且 StatusMatch 官方贡献仍属于 ACTIVE 项目
- **THEN** 用户树继续展示该边
- **AND** 管理审计不再把到期文章计为当前贡献者

#### Scenario: 两篇普通文章期限不同
- **WHEN** 同一边由两篇普通文章贡献且较早一篇先到期
- **THEN** 该边由后一篇继续维持

#### Scenario: 最后一个贡献者到期
- **WHEN** 某边所有贡献者均已到期、归档或失效
- **THEN** 该边从当前统一树消失

### Requirement: 手动归档、恢复和延长均可审计
系统 SHALL 提供普通 ArticleOpportunity 的手动提前归档、恢复和延长操作；手动归档 SHALL 使用 `MANUAL`，延长 SHALL 写入未来的 `visibility_until_at`、设置 `MANUAL_OVERRIDE` 并清除归档字段，所有操作 SHALL 保存操作者、原因和前后值。

#### Scenario: 手动提前归档
- **WHEN** 操作者因活动失效而提前归档一个尚未到期的机会
- **THEN** 该贡献立即从统一树排除
- **AND** 事实、Brief 和操作记录保留

#### Scenario: 恢复尚未到期的手动归档
- **WHEN** 操作者恢复一个当前有效期仍在未来的 MANUAL 归档
- **THEN** 系统清除归档字段并重新允许其贡献

#### Scenario: 恢复已经到期的机会
- **WHEN** 操作者尝试恢复一个可见截止已过去的机会但未提供新时间
- **THEN** 系统拒绝该操作
- **AND** 提示必须提供新的未来可见截止时间

#### Scenario: 手动延长
- **WHEN** 操作者提供新的未来可见截止时间和原因
- **THEN** 策略变为 `MANUAL_OVERRIDE`
- **AND** 归档字段被清除且审计记录包含旧值和新值

### Requirement: 生命周期自动化不得增加模型调用
可见期计算、迁移回填、当前状态检查、归档、恢复、延长和贡献者聚合 SHALL 全部由确定性代码完成，不得触发正文、Brief、关系或图 AI。

#### Scenario: 每日到期任务处理一批文章
- **WHEN** 自动化扫描并归档到期 ArticleOpportunity
- **THEN** 模型调用计数不增加
- **AND** 自动化结果分别报告扫描、到期、手动归档保留和错误数量

