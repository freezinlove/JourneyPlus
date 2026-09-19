# Android 云端测试包

## 构建

在 `clients/android` 执行：

```sh
./gradlew :app:testDebugUnitTest :app:assembleDebug -PserverBaseUrl=https://43.155.217.251
```

输出 `app/build/outputs/apk/debug/app-debug.apk`，版本 1.0.1（2），为调试签名测试包。
服务地址可在登录页修改。旧版本保存的模拟器默认地址会迁移到本次构建地址并清除旧会话；用户自定义地址保留。
兼容本地 `journeyplus_session` 与云端 `journeyplus_cloud_session`，会话仍由 Android Keystore 加密保存。

## 无域名 HTTPS 入口

独立入口配置为 `compose.https.yaml` 和 `deploy/Caddyfile`，部署在服务器 `/opt/journeyplus-https`。
该目录 `.env` 设置 `JOURNEYPLUS_PUBLIC_ADDRESS=43.155.217.251`。

```sh
sudo docker compose --project-directory /opt/journeyplus-https -f /opt/journeyplus-https/compose.https.yaml up -d
```

公网 TCP 80、443 必须在云安全组放行。应用 8000 仍只监听本机；数据库不开放公网。
Caddy 使用 Let's Encrypt `shortlived` IP 证书并自动续期，证书和账户保存在独立 Docker volumes。
入口代理流式响应时立即刷新。GitHub 应用发布和 AIWorkflow 定时器无需改变。

更换服务器 IP 后，需要修改入口 `.env`，重新启动入口以申请新 IP 证书，并在 Android 登录页填写新地址（或重新打包默认地址）。

## 本轮验证

- Android 单元测试和 APK 构建通过；未安装到设备，未做真机验收。
- 2026-09-19 初次配置时，公网 80/443 超时，证书尚未签发，等待云安全组放行。
- 按用户要求暂缓网络验证，HTTPS 入口已停止，避免重复申请证书。用户放行后执行上面的 `up -d` 即可启动；后端与每日任务保持运行。
- 放行后应检查 HTTPS 登录页 200、未登录 `/auth/me` 401，且证书验证不能使用 `-k` 跳过。
- 2026-09-19 用户放行后，入口已启动，Let's Encrypt IP 证书签发成功。补充 `default_sni` 以支持不携带 SNI 的 IP 直连客户端。公网实测登录页 200、证书校验结果 0、未登录 `/auth/me` 401；HTTP 自动跳转 HTTPS。无需重新构建 APK。真机登录、聊天与新闻由用户验收。
