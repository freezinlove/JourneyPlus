# 审计整改实施记录

本轮针对 F01–F11、C01–C04 继续实施。第三方模型调用和探针均为零，没有创建 Git 提交，未修改正式业务库。本轮新建隔离库 `journeyplus_eval_remediation_20260909`，追加验证 migration 0027；性能扩容另用 `journeyplus_eval_perf_20260909`。

当前代码已覆盖启动隔离、端口封装、同步执行隔离、提交期限/所有权、用户与知识读取分离，以及十一项审计复现对应修复。尚不能认定全部完成：需要完成剩余竞争/边界测试、197 项旧行为映射的证据收口、人工 ModelPort 双视角全链路与浏览器检查，再执行最终冻结回归。

已记录的中间证据：

- 原 11 个复现已成为 `tests/test_harness_audit_regressions.py`；同步隔离落地后的针对性集合通过。
- 原 4 项 PostgreSQL harness 回归通过；新增线程响应、SQL/锁等待期限、失去所有权禁止提交，以及真实受限知识角色检查通过。
- Workflow 事务与来源绑定两项原有效行为已恢复为独立测试，冻结 holdout 与跨轮调用匹配也增加了回归。
- 第一轮全回归为 639 passed / 7 skipped / 2 failed；发现的引用索引保留问题已修正，UTC 日期测试假设已统一，后续以最终冻结回归为准。
- 受限知识连接测试发现底层 RouteService 隐式读取会籍，已改为显式 HoldingSnapshot；包含旧有效期判断的 41 项针对性检查通过。
- 197 个删除测试已建立逐条去向及理由，见 `test-retirement-map.json`；历史人工证据不作为本轮通过依据。

原始记录均在 `.secrets/agent-harness/20260909/`，保留失败尝试，不以新结果覆盖。第 12 节任务只有对应实施与验收条件满足后才勾选；本文是过程记录，不是交付审核包。

## 最终系统侧收口

2026-09-09，第 12 节 18 项任务完成；审核包为 [remediation-review.md](remediation-review.md)。原真实模型相关 7 项仍未勾选，不执行第三方模型、探针或 Workflow 调用。本轮改动保留工作区，未创建 Git 提交。

- 最终全回归：**662 passed / 11 skipped / 23 warnings**，92.13 秒；`full-regression-final.txt` 与 `final-tests.xml`。警告来自依赖弃用提示，不是测试错误。
- 真实 PG：**13 passed**，`postgres-final.txt`；涵盖并发、超时、取消开放事务、租约、持久回执、受限知识角色与 Unicode 查询。加上单独 **1 passed** 的 `published-trigger-final.txt`，默认跳过的 PG 条件均已执行。13 项中有 3 项也在普通回归执行，不能简单相加作为独立用例数。
- 人工：核心 7 轮、网页 1 轮、最终冒烟 2 轮完成；12 工具均执行。另有人工 ModelPort 等待时的真实心跳/外部取消，终态 CANCELED、无工具调用。失败尝试仍保留并在新审核包解释。
- 数据：`closure-database-audit.json` 核对 44 张正式知识/来源表无哈希差异，模板原有会籍保持一致；所有人工产物 hash 与工具结果作用域有效，持久 journal 与回执保留。
- 浏览器：8026 在 UnconfiguredModel 下读取真实工作区，图卡/表格/回执刷新位置正确，图节点展示实际条款，带版本简报独立打开，控制台无错误；`browser-workspace.txt/png`、`browser-brief.txt`。
- 效率：`snapshot-benchmark-final.json` 与 `snapshot-benchmark-expanded-final.json`，包含每组 5 次原始测量。新查询保留观察/窗口变化检测，不变引用零正式库扫描。
- 197 项退役映射的文件与函数引用逐个验证存在；前端 JavaScript 语法检查通过；OpenSpec strict 与 git diff --check 通过。

所有原始证据在 `.secrets/agent-harness/20260909/`，最终源码及文件清单另存 `closure-manifest.json`。人工判断和数据库故障注入分开记录，没有将手动决策包装为模型自主验收。
