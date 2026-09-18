# 历史结构测试夹具

这两份文件是可复现的结构基线，不含数据库业务行或本地凭证。

- `models.py`：2026-09-12 原 AIWorkflow 模型，用于 `test_agent_workflow_reads.py` 验证旧结构读取兼容性。
- `schema.sql`：同日放宽约束前的 schema-only 导出，用于 `scripts/verify_relaxed_database_constraints.py`。

原归档仍保存在本机 `doc/database-archives/`，已取消 Git 跟踪。不要用真实数据库数据覆盖测试夹具。
