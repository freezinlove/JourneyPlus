## Why

当前 AIWorkflow 的官方资料、通用文章及文章补充链包含需要保留的生产设计，但仍依赖已退出数据库的旧事件、事实及文章机会表，不能向当前统一知识模型正常生产。依据 `doc/target-system-architecture.md`，本 change 以当前数据库为存储基线，保留已有生产环节和业务策略，调整契约、关联及落库，使简报和匹配图消费同一套正式知识。

## What Changes

- 先建立现有阶段、分支、输入输出、模型调用、重试、复用、图规则的行为对照清单，再按链路逐段实施；不以适配新表为由删步骤、合并模型调用或替换精心设计的生产逻辑。
- **BREAKING**：官方和文章链直接生产活动、知识版本、方案、映射和价格；退出旧业务表写入及后置重复提取桥接，不双写、不建立旧 schema 回退。
- 保留官方 HOME/FAQ/TERMS 分工、确定性表格解析与模型补充；保留普通文章标题筛选、正文一文多活动、逐活动简报；保留关联 StatusMatch 文章只生产补充亮点、不修改官方事实或贡献匹配边的策略。
- 保留原文快照、规范正文、文档级关联、原文链接、活动官网和申请链接。移除字段级引文、证据 ID 及原文匹配发布门槛；结构、业务关联、未知项和冲突处理继续成立。
- 保留模型生成中文简报及现有复用、更新和重试能力，不用简化模板替代。正式版本切换前准备必要产物，失败保留旧发布版本。
- 完整图读取统一事实，保留原图覆盖、可见期、去重和遍历能力；与 Agent 路径工具共享确定性条件和费用判断，不重写 Agent harness。
- 对齐 ORM、迁移入口和调度维护命令；承认当前数据库已实施的约束放松，不重新施加。正常生产路径不新增模型调用，新增调用或业务策略变化须先说明并与用户讨论。

## Capabilities

### New Capabilities

- `aiworkflow-behavior-preservation`: 保留三条生产分支、调用安排和运行语义的改造边界及回归要求。
- `direct-knowledge-production`: 面向当前数据库的统一提取契约、来源身份、目录、阶段记录和原子发布。
- `versioned-workflow-products`: 模型简报、文章补充及完整图对同一版本正式事实的生产和读取。

### Modified Capabilities

无。当前 `openspec/specs/` 没有可直接修改的主规范；历史 change 中的规范仅作为既有行为审计线索，不自动成为当前架构要求。

## Impact

- 主要代码：`models.py`、`knowledge/models.py`、各链路 contracts、`statusmatch/{project_workflow,article_workflow,articles,monitoring,service}.py`、`article_pipeline/`、`briefs/service.py`、`knowledge/{identity,workflow,publication,refresh,reads,routes,briefs}.py`、`membership/`、`automation/`、CLI、知识页面/API及其测试。
- 存储基线：当前 PostgreSQL `clean_0003` 加已执行的价格说明默认值、六项约束放松补丁。主体表不改，不新增限制；补齐迁移可复现性不意味着把数据库重新迁回旧结构。
- 当前业务数据已清空，只保留来源配置与迁移记录。实施测试用按同一 schema 创建的临时库；本提案不启动正常库写入、采集或真实模型调用。
- 范围外：重写生产算法、改来源政策、增加模型调用、重构 Agent 决策/上下文/工具策略、买分链扩展、生产数据重建和完整 Agent 真实网页验收。发现必要业务变化时先讨论，不默认为本 change 已授权。
- 本次只创建规划产物，不实施、不提交 Git。
