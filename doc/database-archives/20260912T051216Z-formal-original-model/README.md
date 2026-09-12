# 正式库切换为原 AIWorkflow 数据模型

2026-09-12，按用户“正式库改用选定的原模型、业务数据保留”的要求完成切换。

## 当前正式状态

- 正式数据库仍为 `journeyplus`，连接地址及 `.env` 未修改。
- 采用 `0061e90` 的原 AIWorkflow 模型，迁移标识为 `0018_membership_agent`，共 31 张表。
- 保留之前实跑所需的两个采集元数据字段：`source_items.document_role`、`document_versions.section_parser_version`。此次没有新增字段或业务约束。
- 主要业务表恢复为 `status_events`、`fact_sets`、`briefs`，以及原有文章分析、补充简报、买分等表；正式库不再包含 `activities` / `application_options` 那套统一知识表。
- 现有配置核对结果：`knowledge_read_mode=legacy`、`knowledge_publish_enabled=false`。

## 数据保留

切换前正式库的业务表全部为空，只有两个来源配置。将之前恢复并实跑的 `journeyplus_old_flyingblue_20260912t042852z` 完整恢复到临时库，再按来源 ID 保留正式库的两个配置，包括 LoyaltyLobby 的采集起始日期 `2026-09-09` 和原有创建、更新时间。

正式库现有业务记录：

| 表 | 记录数 |
| --- | ---: |
| status_events | 1 |
| fact_sets | 1 |
| briefs | 1 |
| document_versions | 3 |
| source_items | 3 |
| event_evidence | 3 |
| statusmatch_watches | 1 |
| statusmatch_watch_pages | 3 |
| statusmatch_change_sets | 1 |
| analysis_runs | 2 |
| job_runs | 1 |
| sources | 7 |

Flying Blue 的 HOME、FAQ、TERMS 原文快照、结构化结果、简报、链接、关联 ID 和历史处理记录均保留。测试库原有的另外五个来源配置也保留，其自动调度均为关闭状态；正式库原有两个来源的设置优先。

## 验证

- 两个原数据库均在切换前完成 PostgreSQL 完整备份；测试库备份实际恢复成功。
- 对所有表的数据按行规范化为 JSON 文本、排序并计算 SHA-256。除明确合并的 `sources` 外，所有表与 Flying Blue 原库的行数及指纹一致。
- 列定义（含类型长度与精度）、约束、索引一致；忽略 PostgreSQL 恢复后消除的已删除列物理序号空位。
- 合并后的两个来源记录逐字段与切换前正式库一致。
- 临时库通过验证后，在管理数据库的一次事务中交换数据库名称。没有终止应用连接；切换时确认没有业务客户端连接。
- 切换后的正式库再次与已验证临时库逐表核对，数据及结构指纹完全一致。
- 使用当前代码只读加载 Flying Blue 组合简报成功；匹配图为 100 个节点、97 条边，97/97 条映射声明完整，无缺失、捏造、重复或方向偏差。
- 本次未重新采集、未调用模型、未改写业务内容。原先记录的简报语义问题仍保留，不属于本次数据库切换的修复范围。

详细结果见 [verification.json](verification.json)，当前正式库仅结构备份见 [schema.sql](schema.sql)。验证文件只记录计数、指纹、图审计及备份位置，不包含完整业务原文或连接密码。

## 备份与恢复入口

完整数据备份放在仓库外，避免将业务数据提交到 Git：

`/Users/xd/Documents/ChatGPT/JourneyPlus-recovery/formal-original-model/20260912T051216Z/`

- `formal-before.dump`：切换前正式库（含两个来源配置）。
- `flyingblue-original.dump`：切换前 Flying Blue 原模型库。
- `formal-after.dump`：切换后的正式库（含配置合并结果）。

原正式库还保留为 `journeyplus_unified_backup_20260912t051216z`，已禁用连接，仅用于回退留档。原 Flying Blue 测试库保持不变。首次准备时用于恢复验证的临时数据库已清理。

若要恢复，先备份恢复操作当时的正式业务数据，再将所需 `.dump` 用 `pg_restore --exit-on-error --single-transaction` 恢复到新建数据库并验证；不要直接覆盖正在使用的正式库。回退至原统一结构需要另行确认，并评估切换后新增业务数据，不能直接用旧备份覆盖新增数据。

## 尚未涉及的代码对齐

本次只切换实际正式库并留档，没有改 AIWorkflow、Agent 或迁移历史。Agent 当前仍存在读取统一知识模型的实现，需要后续适配原 AIWorkflow 模型；数据库切换不代表 Agent 已经适配完成。

仓库现有 Alembic `0019` 及之后的迁移仍包含此前统一模型改造，**不能对当前正式库直接运行 `alembic upgrade head`**。该迁移序列尚未按用户选定的正式模型重新整理。当前结构以本目录的 `schema.sql` 和上述原模型基线为准，旧迁移文件的存在不表示仍选择使用其业务模型。
