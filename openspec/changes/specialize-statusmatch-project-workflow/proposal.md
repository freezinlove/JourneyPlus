## Why

当前 StatusMatch 首页和 FAQ 虽然属于同一个持久化项目，却仍按两篇普通文档分别执行分类、关系判断、事实整理和简报生成，首次接入通常产生六次或更多模型调用以及一套无产品价值的中间事实/简报。StatusMatch 已有可信项目子域、双页 watch 和确定性关闭规则，应改为以项目为单位的专用链路，避免通用文章流程造成重复、误召回和额外成本。

## What Changes

- 为受管 `*.statusmatch.com` 项目新增独立的项目级处理链路，以一个 watch 的当前首页和 FAQ 快照为唯一处理单位。
- 受管 StatusMatch 页面不再调用文档分类 AI；通过抓取与关闭校验后确定性视为 `STATUS_OPPORTUNITY`。
- StatusMatch 项目不再进入候选召回或关系 AI：同一 watch 的页面确定性属于 `current_event_id`，新 watch 确定性创建新活动，不同 host 永不自动合并。
- 首次接入在首页和 FAQ 都就绪后只执行一次项目事实提取和一次简报生成，不再保存仅基于首页的中间事实和简报。
- 项目事实 AI 同时输出项目身份、完整当前事实和正文形式的会籍映射；程序继续解析 HTML 确定性表格并合并两类映射。
- 模型使用 `HOME`、`FAQ` 等证据别名，服务层负责写入真实文档版本 ID 和来源 URL，降低重复 token 和无效证据标识风险。
- 页面更新仍重建一份完整当前项目事实快照；程序比较新旧 FactSet 并记录结构化 ChangeSet，事实未变化时复用 FactSet 和简报。
- 受管 StatusMatch 页面从通用逐文档 `V1Workflow` 中排除，Gmail 邮件继续只承担增量发现。
- 使用真实 StatusMatch 首页和 FAQ 完成端到端验证，并人工核对原页、模型调用、事实、映射、更新说明与最终中文简报。
- 本 change 只实施第一阶段 StatusMatch 专用链路。第二阶段会籍匹配图将消费本链路产出的标准化映射，第三阶段第三方文章将通过精确 StatusMatch 链接附加未被官方简报覆盖的关注点；两者不在本次实施范围内。

## Capabilities

### New Capabilities

- `statusmatch-project-processing`: 受管 StatusMatch 项目的确定性身份、双页项目级 AI 处理、证据别名、混合映射提取、事实变化记录和通用链路隔离。

### Modified Capabilities

无。

## Impact

- 影响 `journeyplus.statusmatch` 的 watch、监控、项目处理和映射解析服务。
- 影响自动化编排与待处理文档选择，受管 StatusMatch 页面将不再进入通用 `V1Workflow`。
- 复用现有页面抓取、内容清洗、文档版本、关闭判定、AI provider、FactSet、Brief、生命周期和审计记录基础设施。
- 需要新增项目级结构化模型、项目处理幂等键、事实 ChangeSet 持久化以及相应迁移和测试。
- 不改变普通第三方文章、普通会籍机会及未来积分买分文章的当前处理路径。
