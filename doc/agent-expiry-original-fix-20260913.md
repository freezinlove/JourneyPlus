# 会籍过期与完整原文读取修复验收（2026-09-13）

本次两条读取链路已修复并在正式服务验收：过期会籍明确排除并解释原因；请求原文时直接交付一篇完整归档正文。不能据此声称模型所有表述都正确：FAQ 的“近期已结束”标题分组仍被模型误读，见下文。

## 实现范围

- 会籍有效期统一按北京时间日历日判断，到期日当天有效，次日过期。返回 CURRENT / EXPIRED / NO_EXPIRY_RECORDED 和判断日期；未填到期日不宣称永久有效。
- 路线准备阶段保留过期项用于解释排除原因，只把有效且可识别身份交给搜索。saved 无有效起点是正常 EMPTY，不再用缺失身份错误诱导模型改写起点。混合会籍只排除过期项，指定 ref 可读取过期记录并续期；日期进入读取缓存指纹。
- 区分 saved 与 explicit 来源并带到路线结果和图中。用户明确要求假设时仍允许假设查询，不新增地区、金额或匹配限制。
- 保留概要和结构化详情的渐进披露。原文目录只列已有文档关联，取消误导性的 source_sections_ref 片段入口。activity.read original 指定一个 document 引用，直接返回该文档的 normalized_body、来源 URL、归档时间及版本。首页、FAQ、Terms 分别算一篇，LoyaltyLobby 一篇文章也是一篇。
- 全文读取跳过普通工具的固定字节裁剪，但仍核对真实模型窗口和剩余输入预算；确实容不下就明确返回 CONTEXT_CAPACITY，不能用片段冒充全文。此例外只可注册给只读工具，其他工具的预算规则保持原有行为。
- 最终提示说明：结构化字段已有答案时直接回答，不为重复确认而读取全文；明确请求原文或具体问题在结构化详情中没有答案时才读取。模型仍自主选择相关文档，不额外安排模型调用。
- 没有数据库迁移、表结构修改、AIWorkflow 生产逻辑修改，也没有恢复逐字段证据校验。

## 正式服务实测

从正式 `/workspace` 页面输入自然语言，使用正式 PostgreSQL、真实 qwen3.8-flash native 和当前 harness；由模型自主调用工具。共 12 轮、37 次业务模型请求、25 次工具调用，运行状态均 COMPLETED、工具调用均 SUCCEEDED。启动探针的 6 次请求单独排除。

用现有 ObservedModel 旁路记录实际输入、HTTP 请求正文和 usage；不替换模型输出、不预写工具调用。读取正式库的工具结果、检查点和展示对象进行复核。全量 JSON 仅位于 Git 忽略的 `.local/agent-audits/expiry-original-fix-20260913/`。

| 轮次 | 场景 | 实际工具链 | 模型请求 / 输入 token | 核对结果 |
|---|---|---|---|---|
| 1 | 空会籍查询 | holdings.read | 2 / 12,100 | 没有编造起点 |
| 2 | 保存临时会籍并查询、画图 | holdings.write → routes.evaluate → display.present | 4 / 30,597 | 仅 Club Avolta 免费，图标明 saved 来源 |
| 3 | 改为过期后重新查询 | holdings.write → routes.evaluate | 3 / 30,321 | 正常空结果，说明 EXPIRED；无 explicit 回退、无新图 |
| 4 | 用户明确要求假设查询 | routes.evaluate → display.present | 3 / 37,108 | 允许假设，结果和图标明 explicit |
| 5 | 续期后恢复匹配 | holdings.write → routes.evaluate | 3 / 44,157 | 恢复 CURRENT，saved 查询重新返回 Club Avolta |
| 6 | 删除临时会籍并检查 | holdings.write → holdings.read | 3 / 49,271 | 只有本次临时记录被删除，所有会籍为 0 |
| 7 | 普通费用问题（说明收紧前） | activity.read overview → activity.read evidence → activity.read original → activity.read original | 5 / 48,492 | 先读结构化字段，随后重复核对首页和 FAQ；全文正确，但回答错误归类部分历史地区 |
| 8 | 核对已结束的标题分组 | 无工具 | 1 / 14,451 | 零工具，利用已有全文纠正历史地区分组 |
| 9 | 明确读取完整 Terms | activity.read original | 2 / 32,154 | Terms 全文逐字交付，一次匹配/12个月条款回答正确 |
| 10 | 明确读取完整 LoyaltyLobby 文章 | activity.read evidence → activity.read evidence → activity.read overview → activity.read evidence → activity.read original | 6 / 43,022 | 全文逐字交付，消费与开卡奖励的区别正确；前两次长查询为空后改短关键词找到文章 |
| 11 | 普通费用问题（最终版本） | activity.read overview → activity.read detail | 3 / 23,772 | 仅 overview → detail，无 original；Silver 的4组价格与数据库一致 |
| 12 | 明确读取完整 FAQ（最终版本） | activity.read original | 2 / 26,337 | 一次 original 返回完整 FAQ；12个月回答正确，但额外展开费用时再次误读已结束分组 |

第一次验收新增的唯一临时会籍为 `holding:c0e25244-b1b9-460e-8e13-c1ef46d7c21f`。创建、改期、续期、删除均经过正式用户消息和 holdings.write，结束后该记录不存在。没有操作其他会籍。

服务重启后的一个 UI 请求遇到启动探针尚未就绪的 503；确认 READY 后通过页面重发，正常完成，没有重复写入。它没有进入模型轮次统计。

## 原文实际交付核对

以下完整正文已在实际发往第三方模型的 HTTP 请求中，与数据库归档逐字相等并校验 SHA-256；不是仅检查材料保存成功或最终回答。字段、链接、表格和注脚没有在读取工具到模型之间被截断。全文指已有的清洗归档正文，不是广告、导航等网页 HTML，也未重新联网采集。

| 文档 | 完整字符数 | UTF-8 字节数 |
|---|---:|---:|
| https://flyingblue.statusmatch.com/ | 1,734 | 1,758 |
| https://flyingblue.statusmatch.com/faq | 9,948 | 9,957 |
| https://flyingblue.statusmatch.com/terms | 4,947 | 4,953 |
| https://loyaltylobby.com/2026/09/11/air-canada-chase-revamped-chase-air-canada-aeroplan-card/ | 2,545 | 2,578 |

共核对实际请求中的 153 对历史调用/结果配对；12 次全文出现（包括后续请求复用）均逐字一致。来源文档数量不等于模型调用次数，后续使用已有全文无需再调用读取工具。

## 自动化检查与边界

- 选定的会籍、原文、原数据模型读取、harness 上下文/内存/执行边界回归：77 passed、6 skipped、2 deselected；图相关 JavaScript 检查 4 passed。6 项跳过为未配置专用 PostgreSQL 故障注入环境，真实正式数据库的正常链路已另行实测。
- 新增测试覆盖：全部过期、混合有效/过期、空会籍、未填到期日、按 ref 读取过期记录、显式引用过期记录不能绕过过滤、用户假设身份仍可用、续期恢复、北京时间跨日缓存失效。
- 原文边界覆盖：约9万字符长文含末尾表格/脚注/链接完整返回；约6万字符结果穿过普通工具字节上限并进入下一次模型输入；超过模拟模型窗口明确报错；空正文、错误归属、一次选多篇拒绝；只读全文例外不能用于写工具。大文和故障注入在自动化测试中完成，没有向正式知识库塞造假长文。
- 另跑的契约检查有两条既存断言仍把工具总数写成12（当前注册11，正式关闭等待后提供10）；与本次新增 original 视图无关，未修改这些旧断言。前述2项排除测试使用已删除的等待金额参数/旧路线服务。本次没有宣称全仓测试全部通过。
- 最后元数据/说明调整后，原文/过期/正式模型结构相关检查再次通过；`git diff --check` 通过。

## 仍存在的模型解释问题

第7轮模型把 FAQ “Recently ended offers”标题下的意大利、美国、加拿大、新加坡/泰国等历史地区当成当前开放地区。核对 HTTP 请求确认标题及其下所有表格都完整、顺序正确；程序结构化字段只保留当前有效的4个区域分组，数据未给错。第8轮用户指出分组后，模型无需新工具即可正确纠正。

最终版本第11轮普通费用查询只使用结构化详情，结果正确；但第12轮按用户要求读完整 FAQ 后，虽然正确回答12个月有效期，又在未经请求的费用补充中重复产生同类分组误读。因此这里只判定完整原文交付修复通过，不判定任意原文解读都可靠。本次没有为掩盖该问题删去历史原文，也没有增加逐字段引用协议。

LoyaltyLobby 前两次较长搜索词为空，随后用 Aeroplan 找到文章并完整读取；属于已存在的关键词检索体验问题，不是正文缺失。

## 数据、预算与交付

业务表逐行前后比对一致：status_events 7、fact_sets 13、briefs 13、article_analyses 1、article_opportunities 1、article_briefs 1、status_holdings 0、agent_wait_goals 7。正式会话、工具回执和展示材料按产品原机制留存。

业务请求累计输入 391,782 token、输出 6,268 token；缓存命中 317,195 输入 token（81.0%）。这是12轮累计，非单轮上下文。保留原有显式系统＋历史缓存，预算配置未改。

验收后恢复正常 `python -m journeyplus.agent.server`，不再安装完整请求观察器；最终 READY、存储 AVAILABLE、路线查询可用，等待功能仍关闭。

修改保留在工作区，未创建 Git 提交。未提交文件主要位于 `agent/adapters`、`agent/services`、`agent/tools`、`agent/harness` 的对应读取与预算文件，另有 `memberships_validity.py`、`knowledge/workflow_knowledge.py`、共享图及两个页面入口、指令、测试和本文。原始审计 JSON 不纳入 Git。
