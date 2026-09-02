## Why

JourneyPlus 当前只把 StatusMatch 项目的 HOME 与 FAQ 作为活动快照，导致只发布在 `/terms/` 的地区、等级和申请费用缺失，也无法稳定区分免费、付费与活动结束。StatusMatch 的三个项目页具有一致的生命周期，因此需要把 TERMS 提升为与 HOME、FAQ 同等必选的当前证据，并在入库前彻底移除重复的公共平台条款。

## What Changes

- 将每个受管 `*.statusmatch.com` 活动项目的 HOME、FAQ、TERMS 定义为必选三页快照；HOME 是活动生命周期的权威来源，HOME 变为结束或候补名单模板时立即归档，无需等待 FAQ、TERMS 同步变化。
- 在持久化、哈希和 AI 处理之前截断 TERMS 中 `StatusMatch.Com Terms of Use` 及其后的公共内容，公共内容不进入数据库。
- 从 FAQ 与 TERMS 的当前项目内容中提取结构化申请路线和费用：标准费用表由程序逐行解析，文字费用由现有项目级 AI 调用补充。
- 合并 FAQ 与 TERMS 的一致、互补和冲突费用；数据库保留 `Recently ended offers` 原文供审计，但其历史费用表不进入当前费用解析或 AI 输入。
- 用明确的匹配申请费用语义判定免费或付费；既无金额也无收费语义时按产品规则判定免费，明确收费但无金额时保留“收费，金额未公布”。
- 将最终路线费用用于机会简报和匹配树连线标签，同时保持地区仅提醒、不限制匹配路径。
- 回填当前受管项目的 TERMS 快照并重新生成事实、简报和树状图费用。

## Capabilities

### New Capabilities

- `statusmatch-terms-pricing`: 规定 StatusMatch 三页快照、TERMS 专属内容持久化、费用提取与合并、免费/付费判定、活动结束识别和产品展示行为。

### Modified Capabilities

无。

## Impact

- 影响 StatusMatch URL 生成、watch page 身份、HOME 优先监控和关闭识别。
- 影响文档清洗与持久化边界、项目工作流证据别名、幂等键和 ChangeSet 来源。
- 新增费用表解析和跨来源费用合并逻辑，但复用现有 `ApplicationRoute`、`RoutePrice` 与一次项目级 AI 调用。
- 影响机会 API、简报以及匹配树连线费用展示。
- 需要数据库迁移、当前项目回填和覆盖三页生命周期、费用语义及展示的测试。
