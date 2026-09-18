# GitHub 手动发布

## 工作方式

仓库 Actions → **发布 JourneyPlus** → Run workflow → 选择 **main** → Run workflow。
只配置 `workflow_dispatch`，推送代码不会上线，也不需要创建 GitHub Release。
工作流文件需要先提交到默认分支 main 才会出现入口。其他分支触发会跳过构建与发布。

GitHub 执行回归测试和镜像构建，推送私有 GHCR 镜像，然后以不可变摘要部署。
版本标签为 Git 提交编号，服务器校验镜像 revision 标签，并验证提交属于 origin/main。
镜像只构建 linux/amd64，适用于当前 x86 服务器。

## 一次性配置

仓库必须启用 Actions；工作流需要 contents:read 和 packages:write（仅构建任务）。
GHCR 新包默认私有，首次发布后请在包设置中确认其私有状态与仓库关联。
发布任务使用当次 `GITHUB_TOKEN` 下载同仓库关联的私有包，不需要长期 PAT。
临时 Docker 登录目录退出时删除；不要把 token 写进日志或命令参数。

在仓库 Settings → Secrets and variables → Actions 配置：

| 名称 | 值 |
| --- | --- |
| DEPLOY_HOST | 服务器公网 IP 或可连接的主机名 |
| DEPLOY_USER | 当前为 ubuntu |
| DEPLOY_SSH_KEY | 独立创建的 Ed25519 部署私钥 |
| DEPLOY_KNOWN_HOSTS | 经可信管理连接核验的服务器 SSH 公钥，格式 `主机名 ssh-ed25519 公钥` |

专用公钥写入服务器 ubuntu 的 authorized_keys，但通过 `restrict` 和 forced command
禁止交互终端、端口转发及任意命令；只接受 `check` 与格式合法的 `deploy 提交 镜像摘要`。
这不是另建系统用户，部署入口需要 ubuntu 的无交互 sudo 权限。
部署权限仍是高权限：有权修改 main 和工作流的人可以发布会在服务器运行的代码。
保留个人管理密钥，部署入口不能代替日常 SSH 管理。

服务器需保留 `~/JourneyPlus` 仓库、只读 GitHub deploy key、`.env.deploy`、`.secrets`，
以及健康的现有应用和数据库。此工作流负责更新，不代替首次建库和数据迁移。
安装入口（在服务器，以 ubuntu 执行）：

```bash
bash scripts/deploy/bootstrap.sh /path/to/deploy-public-key.pub
```

入口固定在 `/usr/local/bin/journeyplus-deploy-entry`。入口自身变化后需重新执行 bootstrap，
普通发布脚本和 Compose 会从选定提交提取，无需覆盖服务器工作区。
安全组需要允许 GitHub 运行器的 SSH 连接；若只允许管理员 IP，GitHub 托管运行器可能被拦截。
不要为排障关闭 SSH 主机身份验证。迁移服务器后同步更新 host、known_hosts 与公钥安装。

## 发布步骤和失败行为

1. GitHub 跑选定的账号隔离、模型适配器、发布脚本测试，再构建 Web 和后端镜像。
2. 服务器取得发布锁，拉取指定镜像，检查提交标签、运行依赖、磁盘和数据库。
3. 暂停应用，生成并检查数据库备份，保存上一应用镜像编号。
4. 执行数据库迁移，启动新应用并等待健康检查。
5. 验证登录页和未登录 API 拦截，保存当前镜像、配置与提交编号。

| 失败阶段 | 行为 |
| --- | --- |
| 测试、构建、下载或预检查 | 不停止现有服务 |
| 备份阶段 | 不执行迁移，尝试恢复上一应用 |
| 迁移失败 | 保持应用停止并报告，不自动恢复数据库 |
| 启动检查失败，数据库版本未变 | 尝试恢复上一镜像 |
| 启动检查失败，数据库版本已变 | 停止应用，等待人工检查与恢复 |

这是单应用容器部署，有维护窗口，正在进行的对话可能中断。
不要在发布期间手动修改容器或取消工作流；取消 SSH 不等同于安全取消迁移。
工作流健康检查不调用真实模型，不代替完整业务验收。

备份位于 `~/JourneyPlus/.local/deploy/backups/`，目录仅管理员读取。
它是服务器本地的发布前快照，**不是 Mac 自动备份或异机备份**。当前不自动删除历史备份，
需观察磁盘使用，确认异机副本可恢复后再制定保留策略。

## 发布后管理与恢复

服务器仓库工作区不会自动 checkout 新提交；实际版本记录在 `.local/deploy/current-revision`。
发布后使用管理包装脚本，保证运行当前镜像和对应配置：

```bash
sudo bash scripts/deploy/manage.sh ps
sudo bash scripts/deploy/manage.sh logs --tail=100 app
# 后续验证并配置每日 Workflow 时可使用：
sudo bash scripts/deploy/manage.sh exec -T app journeyplus run-daily
```

不要直接用旧默认 `journeyplus-app:local` 重建应用，也不要执行 `down -v`。
若数据库结构没有变化，可经确认后以 `.local/deploy/previous-image` 对应的本机镜像恢复应用；
数据库结构变化时先检查兼容性和备份，再决定迁移或恢复，不自动回滚数据。

Actions 页面会显示成功/失败与发布日志；部署阶段还会生成版本与结果摘要。
本次不配置邮件、macOS 推送或站外监控，不能把 Actions 结果误认为电脑已收到通知。

## 首次验收

先用 `check` 验证专用密钥连接及权限，保证不能执行其他命令。
然后人工点击一次发布，核对镜像摘要、备份、健康状态以及登录/Agent。
发布失败分支由本地假 Docker 测试覆盖，不在真实业务数据库上故意制造迁移失败。
