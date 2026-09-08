## ADDED Requirements

### Requirement: Versioned migration without semantic baggage

新harness-2会话 SHALL 通过v3 API建立；旧会话只读保留，可显式导入原文和旧展示，MUST NOT 导入旧语义控制标记或执行pending写入。

#### Scenario: Import old conversation
- **WHEN** 用户在新版继续旧对话
- **THEN** 新模型看到历史来源，旧pending仅作信息，不自动保存或查库。

### Requirement: Legacy decision chains retire

完成验收切换后系统 SHALL 退役旧v1/v2 Agent写入口并收敛核心；非Agent简报与完整图路由 MUST 保留。

#### Scenario: Old client writes after cutover
- **WHEN** 旧客户端调用v2 messages
- **THEN** 收到明确410及新版入口，不重新启动旧Controller。

### Requirement: Real autonomy evaluation

实施 SHALL 完成acceptance.md架构、事务、真实模型/DB/网络/浏览器矩阵，并保留失败；MUST NOT 仅以JSON合法或旧测试通过宣称完成。

#### Scenario: Unseen language
- **WHEN** 真实holdout使用未写入实现的俗称和连续更改条件
- **THEN** 检查实际工具参数和最终结果，不要求固定调用序列，不添加品牌特例来伪造通过。

### Requirement: Additive rollback preserves user effects

迁移 SHALL additive且回滚只切服务路由；成功用户操作和journal MUST 保留，生产发布不属于本change默认授权。

#### Scenario: Rollback after a saved membership
- **WHEN** 切回上一版本服务
- **THEN** 不撤销用户已成功操作，不删除新表或重写提交历史。


### Requirement: Human model-seat review precedes provider acceptance

系统实施 SHALL 先由实施者通过真实 ModelPort 逐步驱动工具，双视角核对上下文、数据、数据库及调用，并完成本地架构收口。第三方模型 API（包括启动探针）MUST 等用户审核系统侧交付并明确批准后才能调用。人工验收 MUST NOT 冒充真实模型评测；真实模型门槛继续保留。

#### Scenario: System ready for user review
- **WHEN** 全部系统侧审查和本地旧链退役完成而用户尚未批准模型验收
- **THEN** 交付人工证据与待验收项，停止在模型接入之前，不运行第三方探针或案例。
