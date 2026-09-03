> 后续方针说明（2026-09-03）：这些已完成任务只交付确定性个性化底座，不包含会籍策略 Agent。后续 Agent 范围见 [会籍策略 Agent 产品方针](../../../doc/personalized-status-match-agent-direction.md)；原有零 AI 调用验收继续适用于既有目录、图谱、简报和详情读取。

## 1. 机会事实与范围

- [x] 1.1 在核心、普通文章和 StatusMatch 契约中加入二值 OpportunityKind 与有证据的 RoutePrice，保持旧 JSON 可读
- [x] 1.2 更新普通文章提示词、Schema 版本、落库转换和事实签名，使现有正文调用输出 OpportunityKind 与路线价格
- [x] 1.3 让 StatusMatch 项目确定性写入 STATUS_MATCH，并在现有项目提取调用中输出路线价格
- [x] 1.4 实现旧事实 OpportunityKind 的保守兼容与普通文章统一图贡献过滤，确认 OTHER 仍照常生成 Brief
- [x] 1.5 实现旧路线价格的确定性兼容解析、全局费用继承和默认中国地区只读提示

## 2. 数据库与自动化

- [x] 2.1 新增 StatusHolding SQLAlchemy 模型及单项目唯一约束
- [x] 2.2 新增 0016 Alembic 迁移，创建 holdings、保守回填 JSON 类型/价格并关闭买分自动调度
- [x] 2.3 更新来源注册表和自动化选择测试，使买分保留手工能力但不再自动运行
- [x] 2.4 增加 SQLite upgrade/downgrade 与 PostgreSQL head 迁移验证

## 3. 个性化领域服务

- [x] 3.1 增加规范化会籍目录读取和 StatusHolding 增删改查服务，拒绝未知自由文本
- [x] 3.2 在统一会籍图上实现多根、无业务深度上限的确定性可达子图
- [x] 3.3 保留循环边、多条入边和交叉引用，并以明确技术预算防止异常大响应
- [x] 3.4 通过 contribution provenance 组装官方和普通文章机会详情、路线、价格、简报与证据
- [x] 3.5 将无映射边的当前 STATUS_MATCH 机会作为 path=null 合并到同一结果集合
- [x] 3.6 实现不按 OpportunityKind 过滤的统一官方/普通文章简报读取服务

## 4. 产品 API 与页面

- [x] 4.1 创建独立产品 FastAPI 应用和稳定的 /v1 响应/请求契约
- [x] 4.2 实现 membership-catalog、status-holdings、personalized-matches、briefs 和 opportunity detail 接口
- [x] 4.3 实现共享产品页面壳、导航和响应式本地 CSS，无外部前端依赖
- [x] 4.4 实现“我的会籍”页面的目录搜索、添加/替换、有效期和删除交互
- [x] 4.5 实现“个性化匹配图”页面的唯一节点、最近到达路径和无闭环卡片树展示
- [x] 4.6 在最近路径连线上展示目标等级的明确原币费用，多路线并列且未知费用不推断
- [x] 4.6 实现展示全部现有 Brief 的“机会简报”页面及搜索/导航
- [x] 4.7 实现包含全部路线价格、中国提醒、条件、期限、证据和入口的“机会详情”页面
- [x] 4.8 增加产品服务 CLI 入口并验证四页面与 API 同源启动

## 5. 验收与交付

- [x] 5.1 增加 OpportunityKind、RoutePrice、旧数据兼容、Brief 不受过滤和中国提示的单元测试
- [x] 5.2 增加 holdings、多根长链、闭环、菱形交叉引用、通配规则和零 AI 调用测试
- [x] 5.3 增加产品 API 与四页面集成测试，包括全部 Brief 和地区多价格详情
- [x] 5.4 使用当前 PostgreSQL 数据验证图、简报数量、Flying Blue/Kenya Airways/GHA 价格和自动化来源状态
- [x] 5.5 更新 README 与运维说明以指向当前总方针、产品启动入口和验证命令，不改写历史基线文档
- [x] 5.6 运行 compileall、全量 pytest、OpenSpec 严格校验和 git diff 检查并记录结果
