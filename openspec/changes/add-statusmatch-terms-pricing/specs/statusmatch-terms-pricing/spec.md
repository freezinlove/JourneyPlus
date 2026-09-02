## ADDED Requirements

### Requirement: StatusMatch 三页原子快照
系统 MUST 为每个受管 `*.statusmatch.com` 项目维护 HOME、FAQ、TERMS 三种页面，并且仅处理同一项目的完整活动三页快照。

#### Scenario: 三页均成功且处于活动状态
- **WHEN** HOME、FAQ、TERMS 均成功抓取并显示当前活动内容
- **THEN** 系统生成一次包含三个文档版本的项目处理任务

#### Scenario: 单页暂时失败
- **WHEN** 任一必选页面抓取失败而其余页面仍显示活动内容
- **THEN** 系统 MUST 不处理不完整快照、不归档活动并保留错误以供重试

#### Scenario: HOME 活动但辅助页暂时异常
- **WHEN** HOME 显示当前活动而 FAQ 或 TERMS 显示异常、过期模板或抓取失败
- **THEN** 系统 MUST 不生成新事实且 MUST 不归档活动

### Requirement: TERMS 公共后半段不得入库
系统 MUST 在内容标准化、哈希、持久化和 AI 处理前移除活动 TERMS 中从精确标题 `StatusMatch.Com Terms of Use` 起的全部平台公共内容。

#### Scenario: 活动 TERMS 包含公共条款边界
- **WHEN** 抓取到的活动 TERMS 包含精确公共条款标题
- **THEN** 下游原始文档、规范化文本、内容哈希和 AI 输入 MUST 仅包含该标题之前的项目专属内容

#### Scenario: 活动 TERMS 缺少公共条款边界
- **WHEN** TERMS 看似仍为活动页面但没有精确公共条款标题
- **THEN** 系统 MUST 将该页面视为抓取错误并且 MUST 不保存整页内容

#### Scenario: HOME 已结束
- **WHEN** HOME 已显示结束或候补名单模板
- **THEN** 系统 MUST 直接归档活动且 MUST 不再要求抓取或保存 TERMS

### Requirement: HOME 权威决定活动结束
系统 MUST 先抓取并判定 HOME 生命周期，再进行辅助页抓取和费用判断；HOME 是活动结束的唯一权威来源。

#### Scenario: HOME 变为候补名单页面
- **WHEN** HOME 显示项目已结束、未来机会登记或 `REGISTER FOR THE WAITLIST`
- **THEN** 系统立即归档当前活动、将生命周期标记为 `EXPIRED` 并跳过 FAQ、TERMS

#### Scenario: 结束页含有通用收费表述
- **WHEN** 已结束的 HOME 仍包含类似 `fees apply` 的平台文案
- **THEN** 系统 MUST 不生成当前付费事实或路线费用

#### Scenario: HOME 抓取失败
- **WHEN** 本轮无法成功抓取 HOME
- **THEN** 系统 MUST 保留上一次有效状态和事实、记录错误并等待重试

### Requirement: 当前费用表确定性提取
系统 SHALL 从 FAQ 与 TERMS 的当前项目费用表中逐行生成 `ApplicationRoute` 和 `RoutePrice`，支持币种前置或后置、范围单元格继承、条件价格及不可用状态。

#### Scenario: 标准地区等级费用表
- **WHEN** 当前表格包含地区或申请范围、Status Tier 与 Application Fee 列
- **THEN** 系统为每个可辨识范围和目标等级生成带原始行证据的价格

#### Scenario: 币种位于金额后方
- **WHEN** 单元格使用 `99 USD` 而不是 `USD 99`
- **THEN** 系统仍解析为金额 99、币种 USD

#### Scenario: 目标等级不可用
- **WHEN** 费用单元格明确写有 `Not Available`
- **THEN** 对应 RoutePrice 的 availability MUST 为 `UNAVAILABLE` 且金额为空

#### Scenario: 历史费用表
- **WHEN** 费用表位于 `Recently ended offers` 标题之后
- **THEN** 系统 MUST 不把该表中的金额、地区或可用性写入当前路线

#### Scenario: 历史费用表与后续当前映射共存
- **WHEN** `Recently ended offers` 下的历史费用表之后仍有独立的当前会籍映射或说明
- **THEN** 数据库 MUST 保留完整项目专属页面供审计，AI 输入和当前费用信号 MUST 移除历史标题及费用表，同时 MUST 保留后续当前映射或说明

#### Scenario: 组合地区中的子地区不可用
- **WHEN** 当前费用表为一组地区列出价格，紧随脚注仅声明其中部分地区不可用
- **THEN** 系统 MUST 将不可用子地区和其余地区拆成不同路线，并只对命中的子地区标记不可用

#### Scenario: 正文声明地区等级不可用但费用表残留金额
- **WHEN** 当前项目正文明确声明部分地区不能申请某一等级，而费用表仍为包含这些地区的组合行保留该等级金额
- **THEN** 系统 MUST 以正文为准拆分受影响地区、将对应等级标记为 `UNAVAILABLE`、清除金额且 MUST NOT 将其标记为规则冲突

### Requirement: 散文费用复用现有 AI 提取
系统 MUST 使用现有一次项目级 AI 调用补充 FAQ 与 TERMS 表格之外的文字费用和条件，且 MUST 不为 TERMS 新增独立 AI 调用或 Agent。

#### Scenario: TERMS 用散文描述基础价与升级价
- **WHEN** TERMS 文字包含基础申请费以及仅适用于部分申请者的额外升级费用
- **THEN** 现有项目级提取同时返回基础价和条件升级价，且系统 MUST 不将两者相加为单一价格

#### Scenario: 已由表格解析的费用
- **WHEN** 确定性解析器已经提取某个费用表
- **THEN** AI 输入包含该结构化结果并被要求仅补充表格外事实

### Requirement: FAQ 与 TERMS 费用合并
系统 MUST 合并 FAQ 和 TERMS 的当前费用，合并一致证据、保留互补路线并显式标记同一范围同一等级的价格冲突。

#### Scenario: 两页金额一致
- **WHEN** FAQ 与 TERMS 对同一范围和等级给出相同金额与币种
- **THEN** 系统保留一个价格并合并两页证据

#### Scenario: 两页各有不同范围
- **WHEN** FAQ 和 TERMS 分别提供互不冲突的地区或会员类型价格
- **THEN** 系统保留全部互补 ApplicationRoute

#### Scenario: 两页当前金额冲突
- **WHEN** FAQ 与 TERMS 对同一范围和等级给出不同当前金额
- **THEN** 系统 MUST 标记费用冲突并保留双方值与证据，不得静默选择其中之一

### Requirement: 免费和付费语义判定
系统 MUST 在完整活动三页快照上按申请费用语义确定免费、收费金额未知或具体价格，并排除通用入会与权益文案。

#### Scenario: 明确免费匹配
- **WHEN** 当前项目内容明确写有 `no application fee`、`no fee payable` 或等价的免费匹配语义
- **THEN** 系统将费用标记为 `免费` 并关联对应证据

#### Scenario: 明确收费但没有金额
- **WHEN** 当前项目内容明确说明 application fees apply、费用会变化、需要支付相关费用或有购买承诺，但未公布金额
- **THEN** 系统将费用标记为 `收费，金额未公布`

#### Scenario: 完全没有金额或费用语义
- **WHEN** 完整活动三页中既没有当前申请金额也没有明确收费或免费匹配语义
- **THEN** 系统按产品规则将费用标记为 `免费` 并注明该判定来源

#### Scenario: 非申请费的免费权益
- **WHEN** 页面仅提到免费注册、免费行李、早餐、Wi-Fi 或赠送权益
- **THEN** 系统 MUST 不把这些表述作为免费匹配证据

#### Scenario: 免费与收费证据冲突
- **WHEN** 同一当前快照同时出现明确免费匹配和明确申请收费语义
- **THEN** 系统 MUST 标记冲突并保留两类证据以供复核

### Requirement: TERMS 一等来源与幂等处理
系统 MUST 为 TERMS 分配独立证据别名，将 TERMS 文档版本纳入项目 ChangeSet 和任务幂等键，并允许历史 ChangeSet 在迁移后保持 TERMS 为空。

#### Scenario: 仅 TERMS 内容发生变化
- **WHEN** HOME 与 FAQ 文档版本不变而 TERMS 文档版本变化
- **THEN** 系统生成新的项目处理任务并重新计算费用事实

#### Scenario: 新 ChangeSet
- **WHEN** 迁移后的完整三页快照处理成功
- **THEN** 新 ChangeSet 同时记录 activity、faq、terms 三个文档版本

#### Scenario: 历史 ChangeSet
- **WHEN** 读取迁移前生成的 ChangeSet
- **THEN** 系统兼容其 terms 文档版本为空而不破坏审计或 API

### Requirement: 费用进入简报和匹配树
系统 SHALL 让机会简报和匹配树消费同一份最终路线费用，并且 MUST 不因地区限制删减匹配路径。

#### Scenario: 路线有具体费用
- **WHEN** 最终路线包含一项或多项当前价格
- **THEN** 简报展示价格明细且匹配树连线展示对应金额和币种

#### Scenario: 基础申请费和条件升级价
- **WHEN** 同一路线同时包含基础申请费和仅面向部分申请者的条件升级价
- **THEN** 简报与匹配树 MUST 明确标记条件价格且 MUST 不用加号将两者呈现为单一应付价格

#### Scenario: 路线免费
- **WHEN** 最终费用判定为免费
- **THEN** 简报和匹配树连线均展示 `免费`

#### Scenario: 收费金额未知
- **WHEN** 最终费用为 `收费，金额未公布`
- **THEN** 简报说明收费但金额未公布且匹配树连线展示 `金额未公布`

#### Scenario: 地区不匹配默认中国
- **WHEN** 项目适用地区未明确包含默认中国地区
- **THEN** 系统仅显示地区提醒，MUST 不隐藏机会、删边或中断后续路径

#### Scenario: 活动已归档
- **WHEN** StatusMatch 事件已因 HOME 结束而归档
- **THEN** 系统 MUST 不在当前匹配树或当前机会简报列表中展示该事件
