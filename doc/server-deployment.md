# 服务器部署（手动操作）

本文件配合 `Dockerfile`、`compose.deploy.yaml` 和 `.env.deploy.example` 使用。
部署配置独立于本地 `compose.yaml`，不合并两个文件。Compose 项目名固定为
`journeyplus-deploy`，避免与本地开发数据库混用。

## 首次准备

在服务器仓库根目录执行：

```bash
cp .env.deploy.example .env.deploy
chmod 600 .env.deploy
mkdir -p .secrets
chmod 700 .secrets
openssl rand -hex 32
nano .env.deploy
```

将生成的随机十六进制密码填入 `JOURNEYPLUS_POSTGRES_PASSWORD`。
密码用于数据库连接 URL，请使用该命令生成的十六进制字符串，避免 URL 特殊字符。
填写模型 API Key；Agent 的模型窗口必须按现有经过验证的配置填写，模板的 0 不能用于对话。
Agent 可使用与 Workflow 相同的 Key，也可以独立配置。不要把 Mac 上的绝对路径照搬到服务器。
不要提交 `.env.deploy` 或 `.secrets`。

将现有 Gmail 授权副本安全传入 `.secrets/google-oauth-client.json` 和
`.secrets/gmail-token.json`。目录可写是为了持久保存刷新后的 token；不写入应用镜像。
不使用 Gmail 时目录仍需存在，授权文件可以等验证 Workflow 前再放入。

## 检查并构建

```bash
sudo docker compose --env-file .env.deploy -f compose.deploy.yaml config --quiet
sudo docker compose --env-file .env.deploy -f compose.deploy.yaml build app
```

不要分享不带 `--quiet` 的完整配置输出，其中可能包含凭证。

## 准备数据并启动

```bash
sudo docker compose --env-file .env.deploy -f compose.deploy.yaml up -d postgres
```

此时先导入本地数据库的备份副本，再启动应用。导入命令需根据备份格式确认，
不要对现有库盲目覆盖。Git 拉取不会迁移任何业务数据或账号。
空数据库直接启动可以创建结构，但不会自动获得原有账号和新闻。

```bash
sudo docker compose --env-file .env.deploy -f compose.deploy.yaml up -d app
sudo docker compose --env-file .env.deploy -f compose.deploy.yaml ps
sudo docker compose --env-file .env.deploy -f compose.deploy.yaml logs --tail=100 app
```

应用启动会执行现有 Alembic 迁移。数据库通过健康检查后才启动应用。
应用健康检查仅验证 HTTP 页面可用，不代表模型和 Gmail 业务验证通过。

默认 Web 仅绑定服务器 `127.0.0.1:8000`。先用 SSH 隧道测试，在 Mac 新终端执行：

```bash
ssh -i /Users/xd/Downloads/journeyplus-tencent.pem -N -L 18000:127.0.0.1:8000 ubuntu@43.155.217.251
```

保持该终端连接，在浏览器打开 `http://127.0.0.1:18000`。
公网发布前另行配置域名、HTTPS 和入口安全组；数据库不映射任何宿主机端口。

## 更新与持久化

更新前先备份数据库至服务器以外的位置，再执行：

```bash
git pull --ff-only origin main
sudo docker compose --env-file .env.deploy -f compose.deploy.yaml up -d --build app
```

数据库保存在 `journeyplus-deploy_postgres_data`，应用本地状态保存在
`journeyplus-deploy_app_state`。凭证通过宿主机目录独立保存。
容器重建不会清除数据卷；不要运行 `down -v` 或清理这些卷。
修改 `.env.deploy` 的数据库密码不会修改已经初始化的数据库密码。
数据卷仍位于此服务器磁盘上，不是异机备份，竞价实例回收可能导致丢失。

此配置不启用定时采集。后续确认手动 `run-daily` 成功后，再单独设置定时器。
