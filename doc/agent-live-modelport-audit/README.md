# 真实入口 + ModelPort 人工替代审计

2026-09-12，北京时间约 14:08–14:12。结果：**真实 Agent 使用失败，阻塞于会话创建，尚未进入业务模型循环。**

## 实际边界

- 使用现有 `journeyplus.agent.server` 正式独立入口、真实 Uvicorn HTTP 服务和工作台网页。
- 使用 `.env` 指向的正式 PostgreSQL `journeyplus`，没有隔离数据库、临时运行数据库、测试夹具或伪造工具结果。
- 唯一替换组件：`AgentModel.stream`，通过 `bridge.py` 在当前进程装配中替换模型类。原配置、初始化 echo 探测、预算估算、工具注册、生命周期、会话存储、维护与恢复任务均沿用现有代码。
- 本轮由 Codex 在收到每个模型请求后写入其响应，没有预设业务工具调用顺序。请求和响应完整保存在 `exchange/`。
- 原 `AgentModel.initialize()` 的两轮 echo 探测已成功。它是启动检查，不是业务工具使用成功。
- 当前配置：native、32768 上下文窗口、联网关闭、legacy 知识模式、用户写入暂停为 false。第三方模型 API 未调用。
- **没有执行 `product-api` CLI**：该命令自动迁移到 head，可能改变用户要求保持的数据库；改用项目已有独立 Agent 入口。不能把本次描述为验证过 product-api 命令的完整启动过程。
- 测试结束后已停止此次服务，未修改应用源代码、配置、数据库或 Git 历史。

## 第一视角：普通用户

1. 打开 `http://127.0.0.1:8013/workspace`，工作台 HTML 与静态资源正常加载。
2. 网页自动请求 `POST /v3/agent/workspaces`，服务返回 **503**，页面显示 `DATABASE_UNAVAILABLE`。
3. 输入并发送：“帮我看看 Flying Blue 现在有哪些会籍匹配机会，先给我简要介绍，需要时再展开条件。”
4. 输入仍在框内，没有回答。控制台报错：

```text
TypeError: Cannot read properties of null (reading 'id')
    at submit (workspace_v3.js:121:43)
    at $.onsubmit (workspace_v3.js:137:92)
```

发送时错误提示被清空，页面未清楚解释发送失败。服务器没有收到本问题的运行请求。

## 第一视角：位于 ModelPort 的模型

- 收到启动探测请求，选择调用 echo(value="probe-ok")；收到其真实回传后回答 probe-ok，完成原有初始化协议。
- **未收到业务问题、业务系统上下文或业务工具列表**：创建会话已失败，根本未进入 Harness 业务循环。
- 因而本次无法实际判断工具选择是否顺畅、结构化结果是否足够、渐进披露是否节省上下文、展示能否成功、多轮记忆是否正确、收尾限制是否妨碍回答。
- 不能用前一轮直接调用工具的审计替代这些未完成项，也不能称整套 Agent 已通过。

## 第三视角：可复核发现

### 1. 阻断：正式库与 Harness 运行存储不匹配（实际失败 + 模式核对）

数据库版本 `0018_membership_agent`，31 张表。

`agent_interactions` 缺少 `revision`、`active_turn_id`、`lease_expires_at`。实际只读 ORM 检查得到 PostgreSQL `42703 UndefinedColumn`：`column agent_interactions.revision does not exist`。

缺少 8 张运行表：

- `agent_workspace_messages`
- `agent_turns`
- `agent_run_checkpoints`
- `agent_artifacts`
- `agent_tool_calls`
- `agent_operation_receipts`
- `agent_delivery_runs`
- `agent_delivery_events`

`agent_run_checkpoints` 实际只读检查返回 `42P01 UndefinedTable`。完整列差异见 `before.json`。会话创建首先失败，因此即使是零工具闲聊也无法启动；问题不在本次模型决策或活动读取。

### 2. 高优先级：就绪状态误导（HTTP 实测）

同一服务的 `/v3/agent/status` 返回：

```json
{"status":"READY","error_type":null,"knowledge":{"status":"AVAILABLE","program_count":27,"tier_count":100,"activity_count":1,"message":null},"ready_for_route_queries":true}
```

模型探测及知识目录可读，不能证明会话、消息、工具回执等运行存储可用。`AgentLifecycle.initialize()` 在模型初始化成功后设置 READY；状态接口没有核对运行存储。后台恢复与维护持续记录 ProgrammingError，也没有让就绪状态体现这项故障。

### 3. 高优先级：会话初始化失败后仍可发送（浏览器实测）

`start()` 失败后调用 `lock(false)`。`submit()` 在进入请求异常处理前读取 `workspace.id`，此时 workspace 为 null，抛出未捕获异常。用户看不到正常失败反馈，且重试发送无法修复缺失会话。

### 4. 高优先级：普通产品启动仍会执行未清理的迁移链（代码审计，未执行）

`cli.py` 的 product-api 分支调用 `prepare_product_database()`；后者无条件执行 `command.upgrade(config, "head")`。正式库停在 0018，但仓库后续迁移包含已弃用的统一活动结构。该启动行为与“保持选择的原业务模型”尚未收口。不能按数据库错误建议直接执行 upgrade head 解决本次问题。

### 5. 后续阻塞风险：会籍记忆尚有另一套字段依赖（代码审计，未做业务写入）

`UserMemory.read/write` 仍使用 StatusHolding 的 revision、program_id、tier_id、source_record、identity_status 等字段；它不等于已适配的路线来源读取。只补运行表，不能就认定 holdings.read/write 和 waiting.manage 已可用。需单独核对并适配，不能为了工具方便重新引入弃用的业务目录。

### 6. 模型自主性仍需实际检验（代码审计，业务未运行）

现有 instructions 允许模型自主选择直答、查询、追问和结束，无固定业务工具顺序。另一方面，调用工具后的 JSON 交付信封、精确字段引用、约束变更逐字引文、交付校验、重复调用保护、资源硬上限仍存在。不能将当前 Harness 描述为完全不限制模型行动。此次没有触发这些机制，未评价它们在实际业务对话中的影响，也未修改它们。

## 下一步顺序

1. 首先解决正式库与 Harness 的运行存储缺口，并处理产品启动自动迁移的冲突；保留已选择的 AIWorkflow 业务模型。
2. 让就绪状态反映运行存储故障，让会话创建失败后的页面可理解、可重试。
3. 再用本桥接从真实网页跑业务对话，审计三个读取工具、按需展开、图卡展示、多轮修改和取消；涉及保存会籍时再实际验证记忆工具。

以上为建议，**本轮未实施修复**，因为用户要求除模型替代外其他全部保持现状。

## 留档与验证

- `server.log`：真实服务器访问记录及后台故障。
- `observation.json`：真实就绪接口、当前非敏感配置和只读数据库错误。
- `before.json` / `after.json`：全部 31 表的列清单、行数及行内容 SHA256，不保存业务原文。
- `verification.json`：前后完全一致；模型请求 2 次（均为启动探测）、业务模型请求 0、业务工具调用 0、会话创建失败。
- `bridge.py`：可复用的模型替代适配器；再次运行应指定新的空交换目录，避免重放本次响应。
- `snapshot.py` / `observe.py`：只读核对脚本。

新增文件全部位于本目录，未提交。没有新增单元测试；本轮证据来自正式数据库、真实 HTTP 和实际浏览器操作。
