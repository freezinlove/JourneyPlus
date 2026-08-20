## ADDED Requirements

### Requirement: 第一版排除攻略文档
系统 SHALL 将以长期教学、方法总结或系统性玩法指导为主要目的的文档标记为 `NONE`，即使文档提及可以获得会籍的路径；系统 SHALL NOT 为该文档创建会籍机会事件。

#### Scenario: 会籍攻略不进入机会流水线
- **WHEN** 文档主要解释如何长期利用信用卡、会籍权益或组合策略获得会籍
- **THEN** 系统将文档标记为 `NONE`，且不输出 `event_hint`

#### Scenario: 具体活动报道仍属于会籍机会
- **WHEN** 文档主要报道某个具体会籍活动的开始、变化、截止或当前实测结果
- **THEN** 系统可将文档标记为 `STATUS_OPPORTUNITY` 并为每个独立活动输出一个 `event_hint`

### Requirement: 事实整理必须限定到单一事件
系统 SHALL 在事实整理输入中提供当前 `StatusEvent` 的活动上下文，以及每份完整材料对应的 hint index 和活动提示摘要。活动上下文 SHALL 只用于限定整理对象，所有非空事实仍必须引用输入正文中的有效证据。

#### Scenario: 同一正文包含两个独立活动
- **WHEN** 同一个 `DocumentVersion` 通过不同 `EventEvidence` 关联到两个 `StatusEvent`
- **THEN** 两次事实整理均可读取完整正文，但分别收到对应事件上下文和对应活动提示，不得混用另一活动的事实

#### Scenario: 多篇正文描述同一活动
- **WHEN** 多个 `DocumentVersion` 关联到同一个 `StatusEvent`
- **THEN** 事实整理收到全部完整正文，并且每份材料携带其与当前活动的提示定位

### Requirement: 已有事实不得被较弱材料删除
系统 MUST 将候选 `FactSet` 与当前事实逐字段协调。当前已知而候选未知的字段 SHALL 保留当前值；当前未知而候选已知的字段 SHALL 接受有证据的新值；相同已知值 SHALL 保留当前字段。

#### Scenario: 新文章遗漏已有截止时间
- **WHEN** 当前事实包含有证据的截止时间，而新候选事实把截止时间留空
- **THEN** 协调后的事实继续保留当前截止时间及其证据

#### Scenario: 新文章补充地区限制
- **WHEN** 当前地区字段未知，而新候选事实提供有证据的地区限制
- **THEN** 协调后的事实接受地区限制并保留对应证据

### Requirement: 不同已知值不得静默覆盖
系统 MUST NOT 使用新的不同已知值直接覆盖当前已知值。第一版 SHALL 将两者保存为明确冲突，并把活动置为需要人工复核。

#### Scenario: 两个来源给出不同费用
- **WHEN** 当前费用与新候选费用均为已知且值不同
- **THEN** 协调后的费用字段设置 `conflict=true`、列出至少两个备选值并保留双方证据，活动状态变为 `NEEDS_REVIEW`

### Requirement: 无实质变化时复用当前输出
系统 SHALL 以字段 value、conflict 和 alternatives 构成事实实质签名，并忽略单纯 evidence 变化。新证据没有产生实质变化时，系统 SHALL 保留事件证据，但 SHALL NOT 创建新的 `FactSetRecord` 或调用 AI 生成新简报。

#### Scenario: 新文章重复已有信息
- **WHEN** 新文章关联到现有事件且协调后的事实实质签名与当前事实相同
- **THEN** 系统保存新的 `EventEvidence`、复用当前 `FactSetRecord` 并复用当前简报

#### Scenario: 新文章增加事实
- **WHEN** 协调后的事实实质签名与当前事实不同
- **THEN** 系统创建下一个 `FactSetRecord` 并基于它生成新的简报记录
