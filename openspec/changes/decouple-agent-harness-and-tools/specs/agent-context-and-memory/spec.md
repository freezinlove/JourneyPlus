## ADDED Requirements

### Requirement: Recoverable context with editable notes

系统 SHALL 保存原消息、工具产物、展示及可修改笔记，并提供本会话历史检索；旧任务标记 MUST NOT 作为执行权限。

#### Scenario: Earlier condition
- **WHEN** 相关目标出现在最近12条消息之前
- **THEN** 模型能够通过workspace.read找回；旧query不会隐式改写新调用。

### Requirement: User authorized membership operations

模型 SHALL 通过独立工具执行有用户原话授权的会籍写入；系统 MUST 校验引用、事务和版本，MUST NOT 对所有明确授权操作追加固定确认流程。

#### Scenario: Explicit save
- **WHEN** 用户明确要求保存一张已说明项目等级的会籍
- **THEN** 模型可调用holdings.write并在成功回执后说明保存完成。

### Requirement: Hypothetical statements do not authorize writes

系统 SHALL 将用户事实、假设和他人信息区别处理；仅网页或模型笔记 MUST NOT 构成用户会籍写入授权。

#### Scenario: Hypothetical holding
- **WHEN** 用户说假设我有这张卡或这是朋友的会籍
- **THEN** 不写用户持有会籍；模型仍可临时查询。

### Requirement: Unresolved holdings stay usable memory

明确授权保存且项目等级原话足够时，系统 SHALL 支持未解析StatusHolding，不得猜目录等级；路线结果 MUST 明示未解析范围。

#### Scenario: Missing catalogue tier
- **WHEN** 用户明确保存但目录缺具体等级
- **THEN** 原始会籍保存为NEEDS_CONFIRMATION，正式目录未新增，后续路径不假装考虑了该未解析身份。

### Requirement: Atomic idempotent writes

用户写入、journal和操作回执 SHALL 在同一事务提交；重复操作、并发更新和取消结果 MUST 可追溯。

#### Scenario: Repeated request
- **WHEN** 相同operation_key和payload在网络恢复后再次到达
- **THEN** 返回原回执，实际记录和revision不会重复改变。
