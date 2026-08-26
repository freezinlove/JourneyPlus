## 1. 现状守卫与测试材料

- [x] 1.1 保存当前来源注册、采集幂等、每日自动化、模型调用计数和会籍链路数据表不受买分处理影响的架构守卫测试
- [x] 1.2 从真实 AwardWallet 目标页面裁剪最小固定 HTML fixture，覆盖三个主分区、顶部推荐子集、相对/绝对链接、有/无截止日期和页面更新时间，不把实时活动数量作为永久业务常量
- [x] 1.3 为页面标题数量不一致、缺少主分区、重复主活动身份、顶部匹配歧义、非法非空日期/百分比/价格和可信零活动页面准备独立失败夹具
- [x] 1.4 增加测试守卫，证明买分模块不导入会籍文章、StatusMatch、FactSet、文章简报或会籍图实现

## 2. 买分契约与持久化

- [x] 2.1 新增买分分类、活动类型、截止状态、快照 Diff 类型、解析诊断、活动解析结果和当前/历史读取的严格 Pydantic 契约
- [x] 2.2 在 ORM 中新增 `BuyPointsSnapshotRecord` 和 `BuyPointsOfferRecord`，包含来源与文档追溯、parser version、数量、签名、买分专属字段和 evidence
- [x] 2.3 为 `(document_version_id, parser_version)`、`(snapshot_id, offer_key)` 添加唯一约束，并为最新快照、按 offer key 历史和 snapshot 子记录查询添加索引
- [x] 2.4 新增 Alembic 迁移和降级，只创建/删除本变更的两张派生表，不修改或删除来源、文档、会籍事件、文章机会、FactSet 和 Brief
- [x] 2.5 验证 SQLite 测试迁移和开发 PostgreSQL 升级/降级，确认已有业务数据与当前迁移链保持完整

## 3. 固定单页来源与正文版本化

- [x] 3.1 实现通用 `SinglePageAdapter`，每次只发现一个稳定条目、设置 `refresh_on_discovery=true` 并只请求配置的 canonical URL
- [x] 3.2 实现最终 URL host/path 边界校验，验证适配器不请求页面内详情链接、affiliate 跳转或外部购买入口
- [x] 3.3 注册 `awardwallet_buy_points_page`、唯一目标 URL、`P1D` 周期和 `single_page` 构建路由，开发阶段先保持自动调度关闭
- [x] 3.4 增加 AwardWallet `article` 正文选择器和广告、目录、信用卡组件等来源专属排除规则，同时保留完整 `raw_body` 供结构解析
- [x] 3.5 增加首次采集、相同内容重新获取复用 DocumentVersion、内容变化创建新版本、HTTP/越界失败不入库和不继续发现链接的适配器与采集测试

## 4. AwardWallet 确定性活动解析

- [x] 4.1 实现航空、酒店和其他交通三个主区块定位以及非表头 `.pt-row` 的完整活动提取
- [x] 4.2 实现项目名、完整优惠原文、截止日、到账时间、详情 URL、购买 URL、分类和字段级 evidence 提取，并将相对链接转为绝对链接而不访问目标
- [x] 4.3 实现 bonus/discount、百分比、购买价格和支持日期格式的有限确定性规范化，保留 `up to` 等完整原文并使允许为空的字段保持空
- [x] 4.4 实现基于详情 URL、购买 URL、分类与项目名回退的稳定 `offer_key`，验证截止日、优惠、价格、到账时间和 Top 状态变化不会改变身份
- [x] 4.5 实现可选顶部 TablePress 表格解析，以 action URL 优先、项目名次之唯一匹配主活动，补充 `top_pick` 和购买价格且不创建重复活动
- [x] 4.6 实现页面更新时间、可选标题声明数量、三个分区总数、活动集合签名和非阻断解析诊断
- [x] 4.7 实现 fail-closed 校验，拒绝缺分区、必需字段缺失、非空字段无法规范化、重复身份、顶部匹配歧义和标题数量不一致，并允许有可信数量信号的真实零活动页面
- [x] 4.8 使用固定夹具验证当前结构的分区、顶部子集、空截止日期、原文限定词、URL、evidence、签名和全部失败边界，证明解析器零 AI 调用

## 5. 快照物化、当前读取与历史 Diff

- [x] 5.1 实现按 DocumentVersion 与 parser version 幂等物化不可变快照和全部活动的事务服务，解析失败不得留下半成品记录
- [x] 5.2 使用现有 `JobRun` 或等价现有运行记录保存解析幂等键、成功、失败、有限重试和安全错误摘要，且不持久化整页内容到错误字段
- [x] 5.3 实现当前解析器版本最新成功快照读取，保证采集或解析失败时上一成功快照仍是当前来源视图
- [x] 5.4 实现按北京时间自然日计算 `ACTIVE / EXPIRED / UNKNOWN`，并把 `is_currently_listed` 与截止状态分离
- [x] 5.5 实现过期但仍列出活动的来源时效异常诊断，不自动删除、归档或改写来源当前列表
- [x] 5.6 实现按 `offer_key` 的结构化历史读取以及相邻成功快照 `ADDED / CHANGED / REMOVED / UNCHANGED` Diff
- [x] 5.7 增加相同输入零重复、新版本历史不可变、parser version 升级并存、活动延期为 CHANGED、活动消失为 REMOVED、零活动快照和失败保留旧视图测试

## 6. 待处理选择与 CLI

- [x] 6.1 实现只选择 `awardwallet_buy_points_page` 且缺少当前 parser version 快照的 DocumentVersion 的有界待处理查询和积压计数
- [x] 6.2 实现买分处理汇总，报告选择、尝试、成功、失败、复用、最新活动数、诊断和安全错误，不依赖 `AIProvider`
- [x] 6.3 增加 `process-buy-points` 确定性处理命令以及 `buy-points-current`、`buy-points-history` 和相邻快照 Diff 的 JSON 读取入口
- [x] 6.4 调整 `run-source awardwallet_buy_points_page`，使其执行采集加买分处理且在没有 AI 凭证时正常工作，其他来源现有路由保持不变
- [x] 6.5 增加 CLI 参数、无 AI 凭证、空数据、当前读取、历史读取、Diff、处理失败和幂等重跑测试

## 7. 每日自动化与可观察性

- [x] 7.1 在每日单轮中加入独立买分确定性处理阶段，与通用文章、StatusMatch 项目、第三方 supplement 和生命周期阶段保持组合入口级隔离
- [x] 7.2 将买分选择、成功、失败、复用、最新活动数和诊断写入每日运行摘要及自动化状态，同时为该来源报告待处理版本数
- [x] 7.3 验证买分处理不增加总模型调用和任何 AI 分项计数，也不占用或修改会籍文章的标题、正文与简报幂等键
- [x] 7.4 增加 AwardWallet 获取失败、解析失败、LoyaltyLobby 失败、Gmail 失败、同日自动化重跑和数据库租约互斥测试，证明各来源和阶段故障隔离
- [x] 7.5 完成自动化测试后启用 `awardwallet_buy_points_page` 的 `P1D` 自动调度，并更新来源播种、自动来源选择和状态断言

## 8. 完整验证与运维交接

- [x] 8.1 运行买分、来源、内容、迁移、CLI、自动化、会籍文章、StatusMatch 和会籍图相关测试，修复全部回归
- [x] 8.2 运行 `openspec validate track-awardwallet-buy-points-promotions --strict` 并修复全部规格错误
- [x] 8.3 对唯一真实目标 URL执行一次受控 smoke，记录观察时间、标题声明数、三个分区计数、顶部匹配数、空截止日期数、代表性原文证据和当前页面更新时间
- [x] 8.4 对真实页面连续运行两次采集与处理，验证第二次无重复 DocumentVersion、快照、活动或模型调用，并人工核对上一成功快照失败保护
- [x] 8.5 更新 README 和买分运维文档，说明唯一 URL、零 AI、数据表、当前/截止状态、CLI、自动化摘要、页面改版排查和关闭调度的回滚步骤
- [x] 8.6 检查最终 diff 和数据库数据，确认本变更未创建或修改 `StatusEvent`、`ArticleOpportunityRecord`、StatusMatch FactSet、文章简报或会籍图贡献，并记录真实验收结论
