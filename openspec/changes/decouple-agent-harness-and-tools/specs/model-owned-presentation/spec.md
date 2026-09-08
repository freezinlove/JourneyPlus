## ADDED Requirements

### Requirement: Model owns final prose and selection

模型 SHALL 直接组织正文及展示对象；服务端 MUST NOT 无条件用模板覆盖文字、按关键词删句或重新推荐排序。

#### Scenario: Selected order
- **WHEN** 模型选择路线B再A并给出理由
- **THEN** 实际图卡与回执保持B、A，程序不依默认评分改为A、B。

### Requirement: Validated rendering with receipts

渲染器 SHALL 校验对象类型、版本、容量及真实图边，并将实际展示回执返回模型；失败 MUST 返回具体错误。

#### Scenario: Unknown display object
- **WHEN** 模型传入不存在的路径ref
- **THEN** 返回STALE_REFERENCE或NOT_FOUND供模型处理，不编造图或静默换卡。

### Requirement: Separate object clicks from conversation actions

卡片节点整体点击 SHALL 打开单一详情并提供focus；下一步建议 SHALL 发送可见自然语言消息，二者MUST分开。

#### Scenario: Followup to clicked node
- **WHEN** 用户点击某步骤后问这个条件是什么
- **THEN** 模型获得真实presentation/object/version，不由正则替它选择另一条路径。

### Requirement: Versioned brief linkage

Agent展示 SHALL 能打开对应版本简报/详情，MUST NOT 启动Workflow生成或修改资料。

#### Scenario: Historical brief
- **WHEN** 用户打开旧路径引用的活动简报
- **THEN** 显示绑定版本并可提示新版，旧费用不被悄悄替换。

### Requirement: Faithful streaming and replay

系统 SHALL 按message_id及event seq交付正文、工具进度、展示、回执和互斥终态；MUST NOT 把整段JSON返回宣传为原生流式。

#### Scenario: Reconnect during answer
- **WHEN** 浏览器中途断开并按after重连
- **THEN** 正文和图卡不重复，已经成功的写入回执不丢失。
