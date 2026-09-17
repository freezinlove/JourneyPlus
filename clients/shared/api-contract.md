# 两端接口与状态约定

权威契约仍在 FastAPI；以下是客户端依赖，不新建服务端事实模型。

| 用途 | HTTP |
| --- | --- |
| 登录 / 用户 / 登出 | POST /auth/login · GET /auth/me · POST /auth/logout |
| 项目等级搜索 | GET /v1/membership-catalog?q=&limit=500 |
| 会籍 | GET/POST /v1/status-holdings · PATCH/DELETE /v1/status-holdings/{id} |
| 新闻分页 | GET /v2/activities?view=cards&limit=20&offset= |
| 活动、路径详情、简报 | GET /v2/activities/{id}[?version_ref=] · /brief |
| 当前工作区 / 新建 | GET /v3/agent/workspaces/current · POST /v3/agent/workspaces |
| 工作区、消息分页 | GET /v3/agent/workspaces/{id}[?cursor=] |
| 发消息 | POST .../{id}/runs（client_message_id、expected_revision、text、subject_refs） |
| 运行事件 | GET .../{id}/runs/{run}/events?after=seq（SSE） |
| 停止 | POST .../{id}/runs/{run}/cancel（idempotency_key） |
| 展示对象 | GET .../{id}/artifacts/{artifactId} |
| 焦点 | POST .../{id}/focus（presentation_ref、object_ref、expected_revision） |
| 展示反馈 | POST .../{id}/presentations/{id}/feedback |

- Cookie 会话；401 清空用户可见状态并登录，409 重新读取修订，410 提示工作区过期。
- 同一重试保留 client_message_id，不能把网络失败等价为未执行。完成后重新读取权威工作区。
- COMPLETED 仅表示运行结束；PARTIAL、FAILED、CANCELED 不转换成成功。
- 免费/付费读取 step.paid；费用属于具体步骤，未知值不编造免费。价格保留币种、条件与冲突。
- 节点合并仅用于排版；每条真实步骤引用独立保留。当前列表不含 version_ref 参数，显式旧引用必须携带它。
- 不从助手普通文字猜测或自动生成图；只读取 PRESENTATION。
- 三页面顺序与图标、色彩和边界来自已确认原型。测试样例只用于验收。
