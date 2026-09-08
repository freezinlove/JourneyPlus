# 人工模型席位与第三视角证据索引

本索引与 [实施总纲](charter.md)、[系统侧审核包](system-review.md) 一起阅读。原始证据位于忽略目录 `.secrets/agent-harness/20260908/`，不提交凭据、原始网页或用户数据。下面目录中的 `request-NNN.json` 是 harness 实际交给模型的 wire 输入，`response-NNN.json` 是实施者看到输入之后提交的下一步；`history.json` 为真实持久化消息。部分旧证据格式不同，在下表注明。

人工结果只证明接口、数据与执行可用，不代表第三方模型能够同样可靠地判断。每项决策只依据相应请求里可见的信息；数据库审查另行进行。

## 本次人工逐步执行

| 证据目录 / 对应要求 | 第一视角决策摘要 | 实际结果与第三视角核对 |
|---|---|---|
| `charter-manual-memory` / A12/A14/W | 用户明确给出原始名称和到期日，直接保存；下一轮只清空日期；再按授权删除并按 holding_ref 读取 | 7 次输入，3 轮完成；3 个 APPLIED 回执、3 条 journal 连续一致；原始身份 NEEDS_CONFIRMATION，最终记录不存在。 |
| `charter-manual-notes` / A07/A11/A13 | 假设身份不写会籍；笔记保存原条件与原话来源；名称未匹配时选择工具实际候选；只修改 free_only，保留禁止挑战 | 8 次输入，2 轮完成；笔记 rev 0→1→2；第二查询 6＋5 页共 11 候选，challenge UNKNOWN，不把它们声称为确定符合“无挑战”；用户操作为 0。 |
| `charter-manual-waiting` / W、T03 首次失败 | 明确创建等待，后台命中后查看、更新起点，再取消 | 旧结果 before 冗余且 after 被裁剪，result_id 残留；保留本次失败，不能因 run COMPLETED 就算语义完整。 |
| `charter-waiting-fixed` / W、T01 | 重新创建→读取实际命中 route_refs→按原 query 更新→取消 | 7 次输入，3 轮完成；后台 check 为 0 模型调用；仅相关 steps，inspect 带 origin_queries；更新后清空结果和签名；3 个用户回执＋1 次后台检查 journal。 |
| `charter-final-tools` / T02、A04/A08 | ANA 广义搜索返回多个项目，依据 program_ref 缩小；空活动如实返回；另一个任务比较 SAS/Hilton，并尝试展开价格 | ANA 4 条目录记录和活动 EMPTY 正常；价格 evidence 过大及后续无关字段导致任务未完整完成，作为修复前证据保留。 |
| `charter-material-fixed` / T03 首次复验 | 独立查询两个起点，按结果引用 compare 与 price evidence，然后读原文 | 价格证据投影修复有效；末条人工 JSON 输入换行未转义，运行 PARTIAL。不是模型失败，也不算完整通过。 |
| `charter-material-final` / T01/T03/P01/A03 | 同类价格对比重新执行；根据返回的原版本与 source_sections_ref 读取价格原文；用户要求后以 Hilton、SAS 顺序 display；再按实际 cursor 读完等待列表，最后转闲聊零工具 | 10 次输入、4 轮完成。目标 tier 未指定，结果分别 Silver Jay 49 USD / Gold Sparrow 149 USD；原文“unless otherwise stated”保留；未声称读完条款。比较顺序和列与实际 UI/回执一致；等待两页总数 2；零用户业务写入。 |
| `charter-network` / N01–N03、A09/A16 | 不查正式路线，按真实搜索链接读取 Marriott 报告，再 parse；另轮按要求测试未配置通用搜索与私网拒绝 | 6 次输入、2 轮完成；报告 137555，提交日 2026-09-02，原始起点 Marriott Bonvoy、目标 Platinum Elite，16 晚/90 天是作者描述，申请日期未知；未把 MATCH 标签当成功或当前官方政策。通用搜索 UNAVAILABLE，私网拒绝，无绕过。 |
| `charter-browser` / P02–P04 | 浏览器提交 SAS→RJ，人工 ModelPort 决定路线与展示；真实点击步骤后，下一轮读取工具实际收到的 focus，并展开证件条件两页 | 6 次输入、2 轮完成；步骤/版本/简报链接一致。加拿大护照要求未改写为居住或国籍要求。刷新顺序问题已修复并复验。 |

最后的界面回放使用同一隔离库的真实工作区与正式前端，后端为 UnconfiguredModel。私有 `/review-fixture` 仅选择既有人工会话，不预编排回答。比较表实际为 Hilton/49 USD/资格未知在前，SAS/149 USD/资格未知在后；点击第一项显示 Hotel Status Match、Silver Jay、49 USD。会籍页面回放依次显示保存、清空日期、删除及对应原文。ANA 与 SAS/国泰/汉莎多轮历史已在正式前端回放；点击“继续展开”从 8 条显示到 11 条，没有模型调用。

## 已有人工证据继续有效的部分

| 目录 | 范围及界限 |
|---|---|
| `manual-review-baseline` | SAS→国泰、汉莎→国泰、恢复 SAS 的真实人工查询与展示；历史后续修复不能由这个旧证据单独证明。 |
| `manual-review-page-fixed` | 11 个 SAS 候选，7＋4 分页，完整读完后展示；修复前 `manual-review-scope-fixed` 保留。 |
| `manual-review-history` | 用 7 轮 fixture 构造窗口前缀，之后人工读取实际投影、查询旧 history 并修改单一条件；前缀不是人工自然对话，明确区分。 |
| `manual-review-query-lineage-r2` | SAS→RJ 后换 Hilton Gold，沿原 query 修改，目标等级仍为空，49 USD Silver Jay 不被前次 Gold Sparrow 锁定。 |
| `manual-review-memory`、`manual-review-null-fixed` | 自然键重复创建 NOOP、到期 null 修复；本次完整增删改进一步核对。 |
| `manual-review-web-paging`、`manual-review-web-controls` | 实际公开网页长正文/链接分页、表单选项显式展开，不把全部选项当报告事实。 |
| `manual-review-wire-decoding` | native wire 容器参数恢复对象后执行，原始参数与规范化结果均保存。 |
| `browser-transport-review` | 本地预设人工响应验证 SSE 断线/重载/取消、部分正文和回执保留；只是传输测试，不冒充实时自主判断。 |
| `browser-import-review` | 合成旧会话显式导入，原文保留、旧 pending_action 不执行、会籍数量不变。 |

## 辅助证据及失败边界

- `charter-final-database-audit.json`：44 张正式业务/来源表与模板逐行哈希一致；9 个本次人工工作区的 artifact 哈希、工具作用域、操作计数、笔记、等待和会籍 journal；包含失败工作区，未删除。
- `charter-rollback.json`：实际 PostgreSQL + 应用生命周期，unified→rollback→legacy，原知识/会籍可读、旧写入口 410、维护写入 503；7 条会籍、17 条 journal、15 条 operation_receipts 前后一致，新表保留。没有生产部署或 downgrade。
- `charter-context-audit.json`：51 份实际人工请求的 wire 字节分布，旧/新完整价格结果大小对比。无 provider usage，不做费用或真实时延声明。
- `charter-final-postgres.txt`：4 项真实 PG 检查通过；并发 start/lease、原子效果与回执、故障窗口、清理与持久效果。中断采用可控注入，非真实机器断电。
- `charter-release-regression.txt`、`charter-release-junit.xml`：最终全回归记录；`charter-final-delta.txt` 为最后接口/schema/查询修复的针对性回归。
- `retirement-manifest.json`、`retired-source-and-tests.tar.gz`、`retired-additional.tar.gz`：旧链及旧测试的退出清单和私有备份，不恢复旧行为来通过旧测试。

此前第三方模型基线及失败保留在原 verification/review 时间线中。当前阶段没有新增第三方模型 API 调用；它们不能替代审核后针对最终代码的新一轮验收。
