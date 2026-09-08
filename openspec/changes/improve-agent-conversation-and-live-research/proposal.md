## Why

2026-09-07 用户真实测试暴露了固定模板覆盖自然回答、连续拒绝偏好后仍追问、事实引用两次校验失败及 47 秒路径请求。参数对照证实默认思考增加延迟；StatusMatcher 只有受控验收，真实客户端及身份映射尚未接通。

## What Changes

- 自然语言正文回答当前问题，结构化详情交给卡片和图，关键限制不隐藏。
- 维护明确查询范围与展示上下文，理解“不限”、序数及点击后的指代。
- 修复事实引用协议，裁剪输入并复用查询，显式关闭常规模型思考且记录完整用量。
- 增加真实阶段事件、经校验的流式正文、完整展示块及断线恢复。
- 在隔离预览接入 StatusMatcher 真实读取、核实项目映射与案例身份，明确失败和样本边界。
- 使用用户完整连续对话、变体、真实数据和模型进行质量与性能验收。

## Capabilities

### New Capabilities

- `conversational-agent-delivery`: 当前任务状态、自然回答、展示指代、引用校验、流式交付及成本观测的一体化修复。
- `live-statusmatcher-integration`: 新工作区研究客户端的真实装配、身份映射及公开网站验收。

### Modified Capabilities

无。此 change 补充尚未归档的 rebuild-membership-knowledge-and-agent，其官方知识版本、用户确认、渐进披露与隔离发布边界继续生效；本 change 明确取代该实现中无条件覆盖正文的策略。

## Impact

涉及 ai/provider、agent/workspace、查询/引用/展示状态、research adapter、product API 与 workspace 前端、测试及验收记录。可能新增临时事件存储迁移，只在隔离库应用。不改正式库、不切换正式消费者、不自动提交或归档。允许隔离预览真实联网读取公开 StatusMatcher 页面，不绕过登录或网站访问控制。
