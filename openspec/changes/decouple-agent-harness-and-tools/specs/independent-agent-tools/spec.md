## ADDED Requirements

### Requirement: Independent discoverable capabilities

系统 SHALL 注册tools.md中的12项独立能力，工具说明描述用途和参数，MUST NOT 要求所有会话按同一工具顺序执行。

#### Scenario: Adding a tool
- **WHEN** 新增合法工具注册与handler
- **THEN** 无需修改runtime的业务if/elif即可由模型调用。

### Requirement: Optional identity reference catalogue

模型 SHALL 可直接使用常识生成名称输入；catalog.lookup SHALL 为可选工具，业务工具 MUST 接受IdentityInput的名称或引用。

#### Scenario: Known colloquial name
- **WHEN** 模型知道全日空的规范名并直接调用业务工具
- **THEN** 工具尝试关联实际记录，不要求先存在catalog调用回执。

### Requirement: Explicit inputs and truthful resolution

业务工具 SHALL 严格执行完整输入或明确query_ref patch，返回effective_input、真实候选和身份缺口，MUST NOT 读取旧聊天标记改变起点目标。

#### Scenario: Target switch
- **WHEN** 模型提交保留起点但更换目标的明确patch
- **THEN** 工具只修改声明字段并返回实际目标，不沿用旧目标等级。

### Requirement: Progressive retrievable data

工具 SHALL 返回有界摘要、版本、覆盖、缺口和可展开引用；detail可直接读取，MUST NOT 因裁剪将未读内容当作不存在。

#### Scenario: Large source result
- **WHEN** 条款和候选超过入模预算
- **THEN** 被省略内容有artifact/cursor可继续读取，模型可继续调用。

### Requirement: Independent public research

系统 SHALL 提供页面发现、网页读取和报告解析；经验研究 MUST NOT 强制正式路径或OptionMapping，也不得根据用户原话关键词否决模型选择。

#### Scenario: Research without published route
- **WHEN** 模型调查未有正式活动映射的一对会籍
- **THEN** 工具可返回原始报告和UNKNOWN可比身份，不制造正式路线。

### Requirement: Knowledge remains read only

Agent读取和研究工具 MUST NOT 调用Workflow采集提取发布或写正式知识身份；网络保护、引用和参数校验 SHALL 保留。

#### Scenario: Directory gap
- **WHEN** 用户名称无法绑定目录
- **THEN** 返回CATALOG_GAP或候选，不能创建正式MembershipTier充当已知身份。
