## ADDED Requirements

### Requirement: Model owns task progression

系统 SHALL 通过通用模型—工具循环处理输入，允许模型直接回答、任意选择已注册工具、根据结果改变方法或追问；MUST NOT 使用业务关键词、强制计划阶段或工具结果类型接管下一步。

#### Scenario: Direct knowledge answer
- **WHEN** 用户只问全日空是什么，模型直接回答
- **THEN** harness返回模型正文，零工具调用合法，不强制查目录。

### Requirement: Every tool result returns control

工具成功、空结果、歧义、失败 SHALL 回送原call_id的模型上下文；程序 MUST NOT 自动把工具状态转换为用户追问或最终结论。

#### Scenario: Model continues after empty search
- **WHEN** 路径工具返回EMPTY而模型选择读取其他资料
- **THEN** 该后续调用被执行，不因已有路径结果强制收尾。

### Requirement: Protocol independent model loop

系统 SHALL 提供runtime.md定义的AgentModelPort及native/json适配；Workflow的模型接口和参数 MUST 保持独立。

#### Scenario: Incomplete streamed arguments
- **WHEN** 模型尚未完成一个工具参数JSON
- **THEN** 系统不执行该调用，完整校验后才记录和执行。

### Requirement: Generic resource controls

系统 SHALL 使用可配置软硬资源预算、取消和重复无进展反馈，MUST NOT 把所有任务限制为三次调用。

#### Scenario: Complex investigation
- **WHEN** 前三次请求已经读取资料且仍需核对，资源预算足够
- **THEN** 模型可继续工具调用；接近硬预算收到资源提示并有收尾空间。

### Requirement: Durable resumable execution

系统 SHALL 以call_id、checkpoint、lease和事件seq支持恢复，并在模型或工具网络工作期间释放数据库事务锁。

#### Scenario: Worker recovery
- **WHEN** 用户写入已commit但worker尚未发送结果即中断
- **THEN** 新worker查操作回执并回送原结果，不重复执行写入。
