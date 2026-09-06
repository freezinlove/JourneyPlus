# 统一入口切换与用户数据恢复

本文件描述已实现的运维接口，不表示正式库已经迁移或入口已经切换。正式执行仍按发布流程批准；不自动开启 StatusMatcher。旧 LoyaltyLobby 快照仅隔离验证。

## 切换状态

`JOURNEYPLUS_KNOWLEDGE_READ_MODE` 默认 `legacy`，三个入口保持原行为；新的 `/knowledge`、`/explore`、`/workspace` 可显式预览。

`unified` 将 `/briefs`、`/matches`、`/agent` 分别导向统一活动、关系探索和工作区。旧业务 `/v1` 返回明确的兼容期停用信息，不把新版对象冒充旧 DTO；会籍表单继续使用已有写入桥接。所有 API 与每日任务进程必须使用相同配置。

`rollback` 是安全降级：暂停推荐和对话写入，保留已发布活动资料的浏览，不恢复已知存在错价问题的旧推荐。`JOURNEYPLUS_KNOWLEDGE_USER_WRITES_PAUSED=true` 可在切换前单独冻结会籍和等待写入。HTTP 层阻止消息中的自然语言确认及专用确认；ORM 层也阻止后台会籍／等待变更，每日等待检查显式 PAUSED。开关不会中断已经开始的请求，因此仍须排空进程后建立检查点。

状态可由 `GET /v2/rollout` 核对。环境变量在进程启动时读取，不能只修改终端变量却保留旧进程。

## 检查点和日志

1. 进入维护窗口，停止调度新任务，排空 API／worker 在途请求和数据库事务；保留已有工作区和独立等待任务。
2. 备份数据库，记录 Alembic revision、源库名称、备份摘要和每表计数／内容摘要，并实际恢复到隔离库校验。部署须先具备 0024 的增量日志表；不进行破坏性降级。
3. 在没有在途事务时记录 `user_business_operations` 的最大 sequence 为检查点。PostgreSQL sequence 分配顺序不是事务提交顺序，因此不能在不停写时仅取 max(sequence) 宣称完整检查点。
4. 启动 `unified` API 和 worker。会籍与独立等待任务的 ORM 创建／更新／删除，在同一事务生成 before/after 日志；业务事务失败则日志一并回滚。日志不是 Agent 记忆，任何模型读取接口都不消费它。

日志仅包含上述两类业务实体；不复制聊天、用户问题、模型输出、StatusMatcher 报告或原始 HTML。等待 query、版本绑定待展示结果和已看候选签名属于独立任务恢复所需状态。临时工作区来源外键与 created/updated 时间不参与重放；业务到期日期、结束时间、状态、revision、会籍身份和任务条件均保留。

## 回滚和重放

1. 停止调度、切换维护／rollback 并重启所有消费者，排空所有在途事务。不要删除新表或日志；不要让旧 worker 并行写入。
2. 从仍保留新写入的库导出检查点之后的操作：

   `.venv/bin/python scripts/user_operation_journal.py export --database <保留新写入的库> --file .secrets/recovery/operations.json --after-sequence <检查点>`

3. 恢复检查点到新的恢复库，保留增量知识表及其目录外键依赖。恢复用户状态与恢复已发布知识不是同一件事；本重放器不会凭会籍名称创建缺失目录，也不会将新等待条件交给旧 schema 的执行器。
4. 先预演：

   `.venv/bin/python scripts/user_operation_journal.py replay --database <恢复库> --file .secrets/recovery/operations.json`

   默认整笔回滚；核对 applied/duplicates 和用户实体快照，再在明确维护配置下加 `--apply` 提交。重复执行按 operation_id 去重；校验和、顺序、字段白名单、目录外键或当前 before 状态不一致均失败，不能强制覆盖。
5. 读取会籍和等待任务，核对新建／修改／取消／已展示状态；复验旧任务不会重新通知。确认新旧日志连续、无未重放事务后才解除写入暂停。迁移降级若日志非空会主动拒绝，不能为通过降级检查清空日志。

这是保留增量结构的消费者回滚，不能承诺把新任务无损塞回只懂旧模型的历史数据库。若要撤回目录或知识版本，还需单独验证依赖闭包，缺失依赖时重放失败并保留原库。旧表退役和日志保留期结束后的清理属于后续明确维护任务，不在本次自动执行。

## 可复现验收

`scripts/verify_user_journal_postgres.py --source <隔离知识库> --output .secrets/<演练目录>` 只读源库，创建两个独立 PostgreSQL 副本，执行 0023/0024 往返、模拟切换后用户操作、重放、重复重放和冲突整笔拒绝。真实结果与局限见 implementation-progress.md；脚本不切换正式消费者。

待完成的发布前条件仍包括真实模型稳定性、剩余官方回填、影子差异清单、旧详情入口替代检查。没有通过这些条件时不得把隔离恢复通过解释为可以上线。
