# StatusMatch 批次浏览器降级

## 行为

每次每日任务或初始化批次创建一个 StatusMatchBatchFetcher，初始使用 HTTP。
检测到明确验证页（包含 HTTP 200 验证页）或 cf-mitigated: challenge 后，当前页改用 Chromium 获取，本批次后续所有 StatusMatch 项目页面使用 Chromium。
普通 403、404、超时不触发切换。下次批次重新使用 HTTP。

监控、Gmail 新发现项目页面、第三方文章关联项目准备共用该批次实例。
手动项目审计、第三方文章处理入口也各自创建并关闭批次实例。
外部注入的测试抓取器仍由调用者管理生命周期。

浏览器延迟启动，每批次复用一个独立上下文，每页关闭标签页，批次 finally 关闭浏览器。
Linux 无 DISPLAY 时临时启动 Xvfb，使用真实有界面 Chromium，不添加 stealth 补丁、不自动解决交互验证码。
只接收同一项目域名的 HTTPS 主文档响应；等待完成的原始响应正文，不读取 page.content()。
主页面获取默认 45 秒超时，仍为验证页则失败；失败不会覆盖旧的有效快照。
现有 HTML 清洗、条款范围裁剪、结构化表格解析、模型提示词和简报流程保持不变。

日志事件 statusmatch_fetch 包含批次标识、去掉查询参数的 URL、获取方式、切换原因、结果、状态码及耗时；不记录 HTML、Cookie 或令牌。

## 本地验证

依赖通过 uv.lock 固定版本。已有 Google Chrome 的 Mac 可运行：

```sh
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_statusmatch_transport.py tests/test_automation.py tests/test_initialization.py tests/test_statusmatch_short_transactions.py tests/test_statusmatch_project_workflow.py tests/test_statusmatch_article_workflow.py
uv run --frozen python scripts/diagnostics/statusmatch_transport.py --channel chrome
```

没有 Google Chrome 时，先安装配套 Chromium，再省略 channel：

```sh
uv run --frozen playwright install chromium
uv run --frozen python scripts/diagnostics/statusmatch_transport.py
```

诊断脚本不连接数据库、不调用模型：对比 FlyingBlue 主页、FAQ、条款的原始响应，经现有清洗/条款裁剪/价格与映射解析后比较结果。
随后用测试替身模拟一次 HTTP 验证页，真实 Chromium 获取后续三页，验证降级过程。
文件保存在 gitignored 的 .local/statusmatch-transport-check，可用 --host / --output 更换项目和输出目录。
如实时页面在两次获取间更新、地区响应不同，比较可能失败；检查 parsed.json，不自动忽略差异。

## 部署

Dockerfile 安装锁定 Playwright 配套 Chromium、系统依赖和 Xvfb；Compose app 的共享内存设为 256 MB。
需要重新构建镜像才能部署，仅 git pull 不会安装浏览器。
本地通过后仍需在服务器验证，因为站点可能针对网络出口返回不同内容。
本次实现不自动开启定时器，不自动发布，不重跑历史 AI 任务。

## 2026-09-19 本地验收记录

- 79 项相关测试通过（批次切换、Gmail 共享、跨阶段共享、资源关闭、每日任务、初始化、项目处理与第三方文章处理）。
- FlyingBlue 活动主页、FAQ、条款：两种方式清洗后的正文一致，程序解析结果一致。
- FAQ：104 条会籍映射、3 条价格路线；条款：3 条价格路线。
- 测试替身触发一次验证后，真实 Chromium 连续获取主页、FAQ、条款，全部成功，只有第一次记录 switched=true。
- 未调用模型，未写入业务数据库；未开启定时任务、未提交或部署。
- 本机官方依赖包下载限速，验收使用校验过 SHA256 的官方 Playwright 1.63.0 Python SDK 与项目已有同版本 JavaScript 驱动，调用本机 Google Chrome。临时 SDK 位于 gitignored 的 .local/playwright-sdk；部署仍使用锁文件和完整浏览器安装。Docker 镜像及服务器的新实现尚未验收。

## 服务器验收更新

2026-09-19 已完成服务器构建、整库恢复后的真实 AIWorkflow 验收：27 次页面获取全部成功、全流程成功。发现并修复页面关闭后的子资源回调噪声，补充单测及本地/服务器连续页面验证，并更新运行镜像。完整数据见 `workflow-rollback-rerun-20260919.md`。
