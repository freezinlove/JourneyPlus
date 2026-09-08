> 当前实施顺序与授权边界以 [实施总纲](charter.md) 为准：先完成系统侧人工双视角验收与本地架构收口，交用户审核；审核明确允许后才调用第三方模型 API（含探针）。原真实模型验收项保留待执行。

# 展示、前端事件与 API

## 1. 模型选择与渲染契约

BlockSelection：
- `type:activity_card|route_graph|comparison|evidence|experience`
- `object_refs:string[1..20]`，全为本会话可访问结果或已发布对象。
- `title?:string(100)`，`reason?:string(500)`，`roles?:[{ref,role:primary|alternative}]`。
- `columns?:[cost,steps,challenge,eligibility,window,validity]`仅comparison；最多6。
- `research_refs?:string[0..8]`关联经验时可给。

display.present严格保留blocks和object_refs顺序。roles必须属于所选对象且最多一个primary，但不自动增加备选或依分数重排。页面可折叠分组与分页，回执说明实际ordered_refs和omissions。超容量整调用INVALID_ARGUMENT提供上限，模型决定减少/分次展示；不静默裁掉最重要对象。

渲染器将现有_assemble拆成不接受用户原话的build_activity/build_graph/build_comparison/build_experience，输入明确对象/列，输出组件DTO。不可调用verified_route_text覆盖正文、recommendation_subset重排、requested_columns解析话术、自动补suggestions。派生图的边必须来自真实route step，费用来自对应版本。非正式推断/外站经验只能在文字或experience/evidence块中明确标注，不混成正式可申请路线。

render receipt：`{presentation_ref,revision,blocks:[{id,type,title,ordered_refs,labels,links:[{object_ref,url,version_ref}]}],next_steps:[],omissions}`。写入artifact并作为tool result回送，因此模型知道真正展示内容。客户端渲染故障发送presentation_error事件，下一轮可见；服务端构建失败直接tool error并允许模型重选，不偷偷换类型。

## 2. 自然正文与后续建议

模型原始text_delta直接交付，不做数字白名单删句，不加一轮固定改写。工具结果显式提供事实来源和未知，指令要求模型区分常识/最新事实/推断；静态规则不声称能审查全部自然语言。违规引用/不存在对象属于结构校验，返回错误；不因提到目录外的常识阻止正文。

下一步建议统一通过display.present的可选`next_steps:[{label,message,subject_refs}]`提供，最多3；可以blocks=[]仅附建议，不要求为了建议画图。适配器将回执转换为assistant message attachment。NativeTools与JsonActions均走同一工具，不在通用模型协议增加会籍展示字段。纯文字可无建议，不必调用工具。点击建议发送用户可见message并附subject_refs；卡片/节点点击只打开详情，不当作用户发送了调查请求。

图卡保留一个主要详情入口。简报链接引用`activity_id+version_id`，打开对应版本；可提示“当前有更新版”但不把旧费用替换成新费用。没有已生成简报时打开同版资料详情并说明简报尚无，不启动Workflow重建。联动URL统一为`/knowledge?activity_id=<UUID>&version_ref=<UUID>&section=brief`；只给knowledge.js增加query参数入口，通过已有`GET /v2/activities/{id}?version_ref=...`打开同版detail并展开brief章节。不是新提取或生成接口。完整图/简报原页面路由继续存在。

## 3. v3 API

新模块product/agent_api.py，单一composition注入RuntimeService；路由不解析用户话术。

| 方法与路径 | 请求/响应 |
|---|---|
| POST /v3/agent/workspaces | `{import_workspace_id?:UUID}` → id/revision/expires/runtime_version |
| GET /v3/agent/workspaces/{id} | messages分页cursor、focus、presentation索引、run状态；禁止默认把全部raw资料返回UI |
| POST /v3/agent/workspaces/{id}/runs | `{text,client_message_id,expected_revision,subject_refs:[],focus_ref?:string}` →202 `{run_id,status}` |
| GET /v3/agent/workspaces/{id}/runs/{run_id}/events?after=N | SSE，断线按seq续订 |
| POST /v3/agent/workspaces/{id}/runs/{run_id}/cancel | `{idempotency_key}` →实际状态与已完成操作列表 |
| POST /v3/agent/workspaces/{id}/focus | `{presentation_ref,object_ref,expected_revision}` →新revision；只记真实选择 |
| GET /v3/agent/workspaces/{id}/artifacts/{artifact_id} | view/cursor，限本会话可见；细节只读 |
| POST /v3/agent/workspaces/{id}/presentations/{presentation_id}/feedback | `{event_id,status:RENDERED|FAILED,error_code?}` →ack；验证对象作用域，按event_id幂等，记录UI实际反馈，不启动新模型run |
| POST /v3/agent/workspaces/{id}/presentations/{presentation_id}/browse | `{cursor,expected_revision}` →明确原快照的下一页，无模型 |

POST run请求hash含text/subject/focus/revision；同client_message_id同hash返回原run，不同hash409。一个workspace同一时间一个active run；运行中第二条消息返回409/RUN_ACTIVE，UI保留输入并提供取消按钮，本change不做隐式插队。focus运行中返回409避免在执行中悄悄改变上下文。用户取消后新消息可继续，保留已经完成的真实操作。

HTTP404不存在、410会话过期/旧入口退役、409版本/运行冲突、422结构错误；业务工具失败通常在run内作为工具结果，不变成HTTP500。错误响应不泄露凭据或内部SQL。

## 4. SSE事件

复用DeliveryRun/Event表及seq逻辑，新增事件名但不改变历史事件：
`accepted`、`assistant.started{message_id}`、`text_delta{message_id,text}`、`tool.started{call_id,label}`、`tool.completed{call_id,status,summary,artifact_refs}`、`presentation.created{presentation_ref,blocks}`、`operation.applied{operation_ref,summary}`、`resource.notice`、`assistant.interrupted`、`completed`、`partial`、`canceled`、`failed`。

最后四类为互斥终态。completed表示模型完成本轮，不等于查遍所有资料。partial说明预算/中断且保留已知结果。浏览器草稿按message_id管理，不把每次模型调用文本覆盖同一DOM。所有seq事件落库后发给订阅者，客户端last_seq去重；恢复不能重复保存、重复图卡或重复追加正文。自然语言直接回答没有tool事件。thinking内容不发前端。

UI增加可取消、恢复中、真实工具label、操作回执；不增加一排与业务无关的调试按钮。耗时细项放原回答依据折叠区。模型主导下仍有简单UI操作无模型，保证点击流畅。

## 5. 前端与模型一致性

模型选择顺序等于render receipt等于用户可见顺序。UI因窄屏折叠可改变布局，不改变推荐排名。点击对象包含presentation_id+object_ref+版本，不能只发送“第一个”交后端正则猜。正文中的自然指代由模型结合最近receipt理解；多个候选无法确定时模型自行问，不写新的序号话术规则。
