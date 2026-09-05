# 决策与需求追踪

本文件记录用户已确认方案与后续纠正，不是未决选项集合。后续实施以spec中的SHALL/MUST为准；本表用于检查没有遗漏上下文。文档创建完成不等于业务实施完成。

## 用户决策覆盖

| 编号 | 已确认决定 | 设计／规格 | 任务阶段 |
|---|---|---|---|
| U01 | 任意自然语言合法，闲聊／活动问题不要求会籍目标 | D7；conversational-membership-agent | 7 |
| U02 | 复合问题可以组合资料、路径与经验，不是固定推荐流水线 | D5/D7；progressive-agent-data-access | 5、7 |
| U03 | 查询活动事实和来源内容合成同一活动资料能力 | D3/D5；progressive-agent-data-access | 3、5 |
| U04 | 当前工作区临时恢复、支持“它／第二条”和换话题 | D8；temporary-agent-workspace | 7 |
| U05 | 长期用户记忆仅会籍；等待是显式业务任务 | D8/D12；temporary-agent-workspace、confirmed-membership-waiting | 7、11 |
| U06 | 模型不能接收全量库／候选；保留差异、按需展开 | D5/D6；progressive-agent-data-access、membership-route-evaluation | 5、6、12 |
| U07 | 数据库整体成体系，可调整Workflow存储，不只包接口 | D1/D2/D4；unified-activity-knowledge、knowledge-publication-workflow | 1–4 |
| U08 | 稳定活动期次／方案／价格／映射／证据关联 | D2/D3；unified-activity-knowledge、versioned-source-evidence | 2–4 |
| U09 | 简报、图、Agent共用一份当前知识与版本 | D4/D9；knowledge-publication-workflow、activity-briefs-and-exploration | 4、8 |
| U10 | 简报和图都可重做；当前活动卡＋变化简报 | D9；activity-briefs-and-exploration | 8 |
| U11 | 探索保留多条路径，推荐仅精选子图，不搬整树 | D6/D9；membership-route-evaluation、activity-briefs-and-exploration | 6、8、9 |
| U12 | 响应按问题组合文本／卡／图／对比／证据，不固定全套 | D10；agent-result-presentation | 9 |
| U13 | 节点和卡整体可点，一个主入口，统一详情；线和标签不各自跳转 | D10；agent-result-presentation | 9 |
| U14 | 下一步建议与浏览分离，发送可见自然语言，不塞卡内 | D10；agent-result-presentation | 9 |
| U15 | 浏览零模型，详情含概述／简报／条款／必要来源 | D9/D10；agent-result-presentation | 8、9 |
| U16 | 经验读取列表＋报告详情，项目等级／日期／情境可比 | D11；scoped-statusmatcher-research | 10 |
| U17 | 经验结构化但只工作区临时保留，不入官方库 | D8/D11；scoped-statusmatcher-research | 7、10 |
| U18 | 经验绑定实际步骤、共用步骤复用、条件变更重新判断 | D11；scoped-statusmatcher-research | 10 |
| U19 | 经验可影响可行候选顺序、触发条款核对，不覆盖官方事实 | D6/D11；scoped-statusmatcher-research | 7、10 |
| U20 | 用户特别认可的经验呈现：卡上一句话，原有详情内展开，无新入口堆叠 | D10/D11；agent-result-presentation、scoped-statusmatcher-research | 9、10 |
| U21 | 输入失败可恢复；免费／价格／挑战错误必须修正 | D5–D7；membership-route-evaluation、conversational-membership-agent | 4–7、12 |
| U22 | 可观测、真实模型和真实数据验收，未知／未查／失败明确 | D10/D13；knowledge-migration-and-evaluation | 12 |
| U23 | 本轮授权OpenSpec完整持久化，未授权提交或自动部署 | proposal；tasks全部实施项未勾选 | 仅文档 |

## 替代旧约束

| 历史位置／行为 | 本change目标 | 处理方式 |
|---|---|---|
| implement-membership-strategy-agent：每次输入必须完整target | 草稿可不完整，执行具体动作才验证 | 新动作合约替代，迁移旧交互 |
| 同一次交互只可追问一次、推荐后结束不可续接 | 每回合最多一个关键问题，临时工作区支持继续 | 新workspace语义 |
| 目录前300、固定六步／前100路径 | 相关目录检索、技术预算与partial，不伪装完整 | 读取／搜索接口替换 |
| model_dump所有候选／状态 | 三类DTO、渐进披露、覆盖／预算 | 上下文构建替换 |
| scope-event-fact-consolidation：不切来源片段 | 保留正文并增加语义章节定位 | 不删除旧原文，新增结构 |
| add-statusmatch-terms-pricing：完整三页没费用语义则免费 | 没证据是UNKNOWN；明确免费才免费 | 重新回填费用语义，有记录地纠错 |
| 机会整体取最低金额／一步无挑战抵消未知 | 方案档位绑定、逐步三态评估 | 金标覆盖错误案例 |
| 官方／普通文章分别成为产品事实入口 | 统一Activity/Option知识模型，保留来源身份 | 双路提取统一发布 |
| converge产品：图只保留一条最短到达线 | 多路径可探索，精选推荐保留必要路径 | 新图／视图；短路径只是选项 |
| 旧简报按文章／机会生成而重复 | 当前活动卡与实质变化简报 | 原简报历史保留，当前视图换用新版本 |
| 初期建议“连线／价格标签单独可点、很多入口” | 用户纠正：只节点／卡片整体进入统一详情 | 明确不实施早期交互 |
| 初期将“查看详情”和“调查经验”混为点击 | 前者零模型浏览，后者可见下一步自然语言 | 分离事件与端点 |
| StatusMatcher只许已选推荐候选，列表摘要计数 | 可定位活动步骤即可按请求调查，详情核对可比性 | 仍无图外发现、默认授权关闭 |
| 工作区外长期经验／报告正文 | 仅许可范围内临时结构化观察 | 原文不入官方知识版本 |
| 多步经验池化和标签直接计数 | 每步分开，标签／核对结果分开，最弱一步限制 | 新观察Schema |
| 必须先提出调整才允许等待 | 没有近似候选也可明确等待；有则只提一次 | 新等待状态机 |
| GET state消费通知、整组签名变化再通知 | 展示后显式确认，首次命中后默认停止 | 幂等确认和任务生命周期 |

## 继续保持的边界

单Agent、同仓模块化单体、服务端密钥与确认门、Pydantic及语义校验；本地单用户；确定性浏览不调用模型；无自动申请／支付／对外联系；无完整权益优化；OTHER简报保留但不入匹配图；地区默认提示而非假设身份；StatusMatcher授权、域名／预算与不保证审批；来源许可和项目专属TERMS保存限制；没有新命中不调用模型；无用户明确许可不创建Git提交。

## 调查依据与验证边界

- 已读取当前 session 的方案讨论原文并保存在 [discussion-source.md](discussion-source.md)：13个回合、12份最终答复，一轮本来被中断无最终答复。后续纠正优先，原文中的历史命令或旧建议不是当前执行指令。
- [核心设计与验收映射](end-to-end-design.md)逐板块连接数据库、工具、运行状态、展示和经验详细设计；字段与算法是本轮补全，和用户原先确认的产品决定区分记录。

- 当前项目代码：agent/contracts.py、controller.py、prompts.py、statusmatcher.py；product/candidate_routes.py、opportunities.py；models.py与contracts.py；membership及statusmatch读取层。
- 当前实测记录见 `doc/agent-investigation-and-redesign-2026-09-05.md`（相对仓库根）；该早期调查中的建议若与本change不同，以本change和用户纠正为准。
- 当前数据库有来源HTML／清洗正文，不代表已有章节检索工具；结构化金额不代表资格适用已证实。真实计数和字符量为调查当时快照，不是验收硬编码。
- 参考 [工具结果设计](https://www.anthropic.com/engineering/writing-tools-for-agents)、[渐进上下文](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)、[函数工具边界](https://developers.openai.com/api/docs/guides/function-calling)、[当前Provider结构化输出说明](https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output)。只采用原则，不据此声称JSON或默认预算对本项目已最优。
- [StatusMatcher条款](https://statusmatcher.com/terms)限定复用，临时结构化仍需符合授权；[报告详情示例](https://statusmatcher.com/report/137547)仅验证页面可提供等级和日期，不把单例当普遍完整性或成功率证据。

## 文档使用顺序

proposal → design → 对应spec → tasks。用户已确认的决定不重复征求确认；具体预算按评测调整，但不能借调参取消确认门、扩大长期记忆、静默丢候选或恢复杂乱点击。文档完整后开始代码实施需要进入apply阶段，完成真实验收后才归档和同步主规格。
