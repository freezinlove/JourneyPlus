## Why

第三方文章偶尔会报道一个具体的 `*.statusmatch.com` 活动，并补充官网简报没有强调的实用观察。当前这类文章会进入通用分类、关系判断和事件合并链路，既可能创建重复活动，也无法把独有信息可靠地挂回受管 StatusMatch 项目，因此第三阶段需要一条低占比、确定性触发且与普通文章解耦的补充路径。

## What Changes

- 从非 Gmail、非受管官网的第三方文章正文中确定性提取具体 `*.statusmatch.com` 项目链接；没有此类链接的文章继续原通用链路，行为不变。
- 对尚未在持久化清单中的链接先建立 watch、抓取 HOME 与 FAQ，并完成官方 StatusMatch 专用链路；已有项目不因文章出现而重复抓取或重跑官网。
- 以项目 host 确定性地把文章挂到 watch 当前活动，不调用分类 AI、候选召回或关系 AI，也不创建独立的普通文章活动。
- 在官方 FactSet 和官方简报完成后，只提取文章中尚未被两者覆盖、且由文章原文支持的“补充关注点”；官方 FactSet 与官方简报记录保持纯净，读取时组合展示补充内容及来源。
- 对同一文章版本、同一项目和同一官方 FactSet 保持幂等；官网事实更新后允许重新比较，并只把与当前官方内容相比仍有新增价值的补充作为当前结果。
- 增加可审计的附件/补充记录、自动化编排、CLI/API 读取面、迁移和测试；支持一篇文章链接多个项目、无新增关注点、处理失败与活动归档等边界情况。
- 使用 LoyaltyLobby 的 Kenya Airways / Accor 真实文章及其链接的 StatusMatch HOME、FAQ 做端到端验收，并人工核对链接路由、事实差异、来源证据和最终组合简报。

## Capabilities

### New Capabilities

- `statusmatch-third-party-highlights`: 确定性发现第三方文章中的 StatusMatch 项目、接入缺失官网项目、附加有证据且不重复官方内容的关注点，并提供组合简报与审计能力。

### Modified Capabilities

无。

## Impact

- 影响 `journeyplus.statusmatch` 的第三方文章路由、补充提取、项目读取与审计模块。
- 影响普通文档 pending 选择、每日自动化、受控初始化和 CLI/review API 的编排及汇总。
- 新增第三方附件/补充持久化表及 Alembic 迁移，但不修改现有官方 FactSet、Brief 或会籍匹配图的数据契约。
- 复用现有 StatusMatch 链接规范化、watch、HOME+FAQ 监控、项目工作流、来源采集与 AI Provider；不新增外部依赖。
