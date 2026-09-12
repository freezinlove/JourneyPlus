# 第三方模型与显式缓存实测

2026-09-12。用户明确授权接回第三方模型并显式开启缓存。

## 配置与实现

使用原有 Agent 配置：`qwen3.8-flash`、百炼北京兼容接口、native 工具协议、thinking=false、temperature=0.2。未更换模型，未修改业务提示词、工具定义、数据库模型或 AIWorkflow；联网工具保持原来的关闭状态。

新增 Agent 专用配置 `JOURNEYPLUS_AGENT_EXPLICIT_CACHE`，代码默认 false；本地 `.env` 已明确设为 true。普通生产入口同样读取这个配置，不依赖本次验收脚本。更换不支持该参数的供应商时应关闭此开关。

模型适配层按供应商协议将文本保持为稳定的 content 块，在系统前缀和当前最后一个有正文的消息上添加 `cache_control: {type: ephemeral}`。工具定义参与前缀缓存；没有建立本地答案缓存或跳过模型调用。消息角色、内容、引用、工具调用/结果配对均保留，缓存元数据不写入业务数据。native 与 JSON actions 两种适配都有测试，缓存设置计入恢复配置摘要；预算仍按完整输入计量，不把命中 token 从上下文预算中扣除。

依据：[百炼上下文缓存](https://help.aliyun.com/zh/model-studio/context-cache)、[显式缓存最佳实践](https://help.aliyun.com/zh/model-studio/explicit-cache-guide)。供应商当前要求至少 1024 token 才创建缓存，ephemeral 有效期 5 分钟；实际命中以 usage 为准。工具缓存标记加在 messages 中，而不是工具 Schema 上。

## 实测方式

观察脚本现位于 `scripts/observe_agent_product.py`，使用正常 `product-api` CLI、正式 PostgreSQL 和浏览器工作台。观察器仅记录实际 ModelPort 输入、发往供应商的请求正文、真实模型事件及 usage；调用实际 `AgentModel.stream`，没有提供或修改模型回答，没有预设工具调用顺序，也没有隔离数据库。

模型自行处理四轮用户输入：

| 场景 | 实际执行 | 结果 |
|---|---|---|
| Flying Blue 简要介绍，只用文字、不保存 | activity.read 概览及详情 | 自然语言回答，没有图卡或会籍写入；文案存在下述问题 |
| 假设 Aeroplan Elite 50K、希腊、EUR 250，要求路线图 | catalog.lookup、routes.evaluate search/inspect、display.present | 图卡实际显示 Gold、EUR 199；最终回答有下述误述 |
| 其他条件不变，预算改为 EUR 100，不再画图 | 原 query_ref 的 max_amount patch，附当前用户原话 | 正确保留会籍/目标/居住地，返回空结果，未新建图卡 |
| 明确保存临时测试会籍，核对后删除 | holdings.write create、holdings.read、holdings.write delete、holdings.read | 两次 APPLIED 回执，最终确认记录不存在 |

总计 4 个运行均为 COMPLETED，11 次业务工具调用均成功，1 个实际图卡，0 个 RESPONSE 信封。两轮启动探针加 15 次业务请求，共 17 次实际供应商请求。运行成功不等于回答的业务语义全部正确。

## 显式缓存验证

首个业务请求创建 8,263 个缓存 token；下一次请求命中 8,263 个缓存 token，并创建新增部分。供应商返回 `cache_type=ephemeral`、`cache_creation_input_tokens` 和 `cached_tokens`，与实际 wire 请求中的缓存标记相符。

| 范围 | 模型请求 | 输入 token | 缓存命中 token | 新建缓存 token | 输出 token |
|---|---:|---:|---:|---:|---:|
| 业务请求 | 15 | 176,036 | 143,438 | 32,478 | 2,404 |
| 含启动探针 | 17 | 176,499 | 143,438 | 32,478 | 2,431 |

业务输入缓存命中比例 **81.48%**。命中量和创建量包含在输入量中，不能再次相加作为总输入；这也不是费用折扣百分比或账户账单结论。没有为提高命中率额外发送重复业务请求或填充提示词。

## 发现的问题

1. 活动介绍把输入中的“香港、台湾、中国大陆”扩写成“港澳台、中国大陆”；对应工具结果不含澳门，扩写缺少依据。原结果在 `005.input.json`，回答在 `005.output.json`。
2. 路线最终回答说“数据库收录的映射表未逐条列出 Aeroplan 条目”。实际上刚返回的 inspect 结果明确含 Aeroplan Elite 50K → Flying Blue Gold、`mapping-9` 和官方 claim 引用；这属于模型误读/误述，不能由工具成功掩盖。最终请求 `010.input.json` / `010.wire.json` 中仍完整保留该映射，回答在 `010.output.json`。
3. “简要介绍”的回答偏长，还显示了 `UNKNOWN` 等内部状态文字，未完全达到预期的简洁自然语言体验。

本轮先记录这些真实模型问题，没有为了让测试通过而改提示词、恢复回答信封、加品牌规则或重写工具。后续可依据这批实际输入输出进行小范围改进与复验；不能宣称 Agent 已全面验收通过。

## 数据、测试与留档

原始记录已移至仓库外的本地目录 `/Users/xd/Documents/ChatGPT/JourneyPlus-recovery/agent-real-model-cache-20260912/`，不纳入 Git。归档包含本次原始报告和脚本副本，共 76 个文件，迁移前后逐文件 SHA-256 一致。下面的 JSON 和日志文件名均相对于该归档目录；它们不是程序或自动化测试的依赖。

- `before.json` / `after.json`：28 张非 Agent 业务表的列清单、行数和逐行内容指纹完全一致，临时会籍已删除；没有修改已有业务知识。
- `verification.json`：正式库中的运行、工具状态、操作回执及逐请求 usage 汇总。
- `workspace-*.json`：最终对话和图卡引用。正常验收产生的对话、工具快照和操作回执保留在正式库。
- `exchange/*.input.json`：实际投影后的上下文与工具定义；`*.wire.json`：发给供应商的请求正文，未记录认证头；`*.output.json` / `*.metrics.json`：真实模型事件和 usage。
- 单元/集成回归命令：`.venv/bin/python -m pytest tests/test_agent_prompt_cache.py tests/test_harness_model.py tests/test_agent_natural_language.py -ra`，结果 **27 passed**，5.71 秒。验证缓存开关、请求格式/前缀稳定、内容与角色不变、两种模型协议、usage 保留及自然语言业务链路。`git diff --check` 通过。

测试观察服务已停止。显式缓存配置保留在本地 `.env`，正常启动仍使用真实第三方模型。代码、测试及文档未提交 Git。

## 后续记录方式

在仓库根目录显式运行 `.venv/bin/python scripts/observe_agent_product.py product-api --host 127.0.0.1 --port 8013`。该命令启动正常产品服务，使用正常数据库及模型配置。

新记录默认写入 `.local/agent-audits/<UTC时间>-<唯一标识>/exchange/`，该输出目录已被 Git 忽略。可通过 `JOURNEYPLUS_AGENT_AUDIT_DIR` 指定其他本地输出根目录；自定义位置应选择仓库外目录。每个模型实例使用独立目录，避免覆盖历史记录。普通产品入口不会开启此文件记录。

`doc` 保留验收结论，`scripts` 保留可复用观察脚本；完整请求、会话、指标和日志只作本地审计资料。若未来需要回归样本，应另行提取最小、脱敏的测试 fixture。
