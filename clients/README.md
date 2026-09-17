# JourneyPlus 独立客户端

Web 是 React + TypeScript + Vite，使用 Radix Dialog、TanStack Query、CSS Modules；Android 是 Kotlin + Jetpack Compose 原生应用。两端连接同一 FastAPI，不访问数据库，不启动 AIWorkflow，不自行推断匹配资格。

## Web

后端继续按根目录说明启动产品 API（默认 8000）。已有库不要因运行前端而迁移、清理或重建。前端开发：

```sh
cd clients/web
npm ci
npm run dev
```

访问 `http://127.0.0.1:5173`。默认代理到 `http://127.0.0.1:8000`，也可以在启动时设置 `JOURNEYPLUS_API_URL`。API、Cookie 和事件流经同源代理，不放开后端 CORS，不把登录密钥交给前端保存。使用已有账号；没有新增注册流程。

```sh
npm run build
npm run preview
npm test
```

静态产物为 `clients/web/dist`。部署示例 `deploy/nginx.conf` 应放入运维配置的 HTTPS server，静态文件与 FastAPI 分开部署；反向代理传递 Host、关闭 SSE 缓冲。FastAPI 只信任自己的代理地址及 forwarded headers。历史 `/knowledge?activity_id=…&version_ref=…` 链接在新前端保留对应版本。现有服务端 HTML 暂保留，便于逐步切换和回退；新域名根目录应指向 dist，不指向旧 HTML。

## Android

JDK 17、Android SDK 35；工程附带 Gradle 8.11.1 wrapper，AGP 8.9.2、Kotlin 2.1.0。在 Android Studio 打开 `clients/android`，或：

```sh
cd clients/android
./gradlew :app:assembleDebug
```

APK：`app/build/outputs/apk/debug/app-debug.apk`。登录页填写服务地址：

- Android 模拟器：`http://10.0.2.2:8000`。
- USB 真机：执行 `adb reverse tcp:8000 tcp:8000` 后填写 `http://127.0.0.1:8000`。
- 线上：使用部署后的 HTTPS API 地址。

只有 Debug 包允许 HTTP，Release 只允许 HTTPS。Session Cookie 使用 Android Keystore 加密后保存，切换服务器或退出时清除，不保存密码；应用备份关闭。发布签名、应用商店上架和公网服务器部署不在本次本地实施中。

## 功能与状态

- 登录、登出及失效处理；会籍统一列表、搜索规范目录、添加、编辑、删除和有效期。
- 会籍新闻分页；当前新闻不锁旧版本；路径引用与历史链接锁定 version_ref。
- v3 工作区恢复、新对话、SSE 流式回复、停止、错误反馈；模型选定的图与资料展示。
- 匹配图只将已有路线排版，保留起点、分支、中转与每条边的活动/版本。节点打开申请详情，不把目标节点费用当成所有路径的费用。小屏横向滑动，纵向手势继续滚动页面，不做全屏展开。
- 深浅色；Web 三页面统一宽度；Android 顶部图标导航，详情/会籍为返回，系统返回与 IME 发送。

## 隔离验收

以下服务只在临时 SQLite 中创建测试账号/资料，**不读取 `.env` 或真实数据库**；模型是测试替身：

```sh
# 仓库根目录，终端 1
PYTHONPATH=.:src .venv/bin/python clients/test_server.py
# 终端 2
JOURNEYPLUS_API_URL=http://127.0.0.1:8019 npm run dev --prefix clients/web
# 终端 3（使用已安装 Chrome）
cd clients/web
npx playwright test
```

测试账号 `client-test` / `Client-test-2026!` 仅在隔离服务有效。不能用隔离验收结果声称真实模型完成推荐，也不能把测试新闻当真实活动。

技术参考：[Vite](https://vite.dev/guide/)、[Android Gradle Plugin 8.9](https://developer.android.com/build/releases/agp-8-9-0-release-notes)、[Compose 版本管理](https://developer.android.com/develop/ui/compose/bom)。

## 本次验证记录（2026-09-16）

- Web：TypeScript 与 Vite 生产构建通过；图布局的分支、合并、多起点与版本引用共 2 项测试通过；Playwright 对隔离 FastAPI 的登录、SSE、刷新恢复、新闻详情、会籍保存、主题与登出流程通过。npm audit 为 0 项漏洞。
- Android：assembleDebug 与 lintDebug 通过；Lint 仍有依赖更新、目标 SDK 和 KTX 建议等非阻断提示。已在 Pixel 6 模拟器安装，验证 Cookie 恢复、发送消息及流式回复、新闻详情、系统返回、会籍编辑保存。
- 尚未做真实模型与生产数据的验收、真机多尺寸验证和签名发布。隔离服务仅用于前端联调；正式使用按上方配置连接现有产品 API。
- 本次只新增独立客户端、共享契约与部署示例；保留旧 HTML 入口，没有修改真实数据库、AIWorkflow 或 Harness。
