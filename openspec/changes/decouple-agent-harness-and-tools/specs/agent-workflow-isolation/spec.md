## ADDED Requirements

### Requirement: Separate business ownership

Agent与AI Workflow SHALL 使用独立业务控制链；共享范围仅为稳定知识读取、用户数据服务边界及版本化展示引用。

#### Scenario: Workflow is stopped
- **WHEN** Workflow采集提取进程未运行
- **THEN** Agent仍能对已发布数据查询、回答及展示。

### Requirement: Dependency boundaries are enforced

harness MUST NOT 导入业务模块或SQLAlchemy；Workflow MUST NOT 导入Agent运行核心；tools SHALL 通过显式服务port执行。

#### Scenario: Dependency audit
- **WHEN** 运行架构测试
- **THEN** 检测禁止的导入即失败，增加工具无需修改harness业务分支。

### Requirement: Model and publication settings are isolated

Agent模型协议/参数/网络开关 SHALL 独立于Workflow；Agent操作 MUST NOT 写已发布活动、简报或全图数据。

#### Scenario: Agent configuration changes
- **WHEN** 切换Agent模型或启用Agent研究
- **THEN** Workflow提取参数、发布行为和采集开关保持原值。
