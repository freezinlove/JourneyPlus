# 每日 AIWorkflow 与 COS 备份

## 行为

- systemd 每天 **Asia/Shanghai 13:00** 执行当前部署容器中的 `journeyplus run-daily`；不依赖 Mac 或 SSH 会话。
- `Persistent=true` 在服务器恢复后补触发一次，不逐日补跑。业务失败标记失败，不自动再次调用模型。
- 每 30 分钟单独重试待上传备份；不会重跑 AIWorkflow。
- 任务与发布共用 `.local/deploy/release.lock`，锁冲突 60 秒后重试。长任务期间发布最多等待原有 900 秒，超时可稍后重新发布。
- 数据包包含 `database.dump`、脱敏 `workflow.log`、`result.json`、`SHA256SUMS`。这是数据库备份，不含 Gmail 凭据或 `.env.deploy`，迁移时必须单独安全迁移这些配置。
- COS `journeyplus/latest/backup.tar` 始终保留最新完整数据包；`journeyplus/history/<运行ID>.tar` 保留 **7 份不同的历史包**。不设按天删除的生命周期。
- 候选包先上传 `journeyplus/pending/`，回读校验后才晋升。旧最新包先归档，最后清理超额历史；操作中可能短暂超过八份，成功完成后最多八份。中断后由上传重试收敛。
- 数据库导出失败时，仅上传日志/结果到 `journeyplus/failures/`，最多 7 份，不替换最新数据库备份。AIWorkflow 失败但数据库导出成功时，仍保存完整数据库包，结果明确记录业务失败。
- 本机保留最近 8 个已上传批次，尚未上传的批次不会自动清理。磁盘不足 1 GiB 时拒绝开始新任务，需要人工处理。
- 当前简单上传上限为单包 5 GiB，超限会失败并保留本机文件，后续需增加分块上传。日备份不包含上次备份后新增的实时数据。
- 安装/发布不自动启用定时器。COS 权限不等于定时任务已经开始。

## 首次安装

服务器已有 Docker、运行中的部署、`.env.deploy` 和 `.secrets`。CVM 绑定 `JourneyPlusBackupRole`，允许备份桶列表读取与 `journeyplus/*` 对象读写删除。

```bash
cd ~/JourneyPlus
sudo bash scripts/automation/install.sh "$PWD"
```

配置文件 `/etc/journeyplus/backup.env`（不含密钥，访问凭据由 CVM 实例角色自动获取）：

```dotenv
COS_BUCKET=journeyplus-backups-1395705638
COS_REGION=ap-seoul
COS_ROLE=JourneyPlusBackupRole
```

确认 `.secrets/google-oauth-client.json`、`.secrets/gmail-token.json` 存在且容器能读写；不要提交这些文件到 Git。先进行不调用模型的备份验收：

```bash
sudo bash -c 'set -a; source /etc/journeyplus/backup.env; set +a; python3 /opt/journeyplus-automation/daily.py backup-only --root /home/ubuntu/JourneyPlus'
```

下载 COS 最新包，先核对 `SHA256SUMS`，再向**独立验收数据库**恢复并核对数据；绝对不要为验收覆盖正在使用的数据库。

手动完整运行一次（会访问数据源并消耗模型配额）：

```bash
sudo systemctl start journeyplus-daily.service
sudo journalctl -u journeyplus-daily.service -n 60 --no-pager
```

完整验收后启用：

```bash
sudo systemctl enable --now journeyplus-daily.timer journeyplus-retry.timer
systemctl list-timers 'journeyplus-*' --all
```

如果本地还有 Codex 每日采集任务，先停用旧任务，避免两个不同数据库分别采集。服务执行中不要强制重启 Docker 或杀死服务；云端模型调用不一定随本机进程立刻终止。

## 日常操作

```bash
# 状态与运行阶段（详细业务输出在数据包和本机 workflow.log）
systemctl status journeyplus-daily.timer journeyplus-daily.service
sudo journalctl -u journeyplus-daily.service -n 80 --no-pager
# 仅补传待上传包
sudo systemctl start journeyplus-retry.service
# 暂停未来定时触发，不中断当前运行
sudo systemctl disable --now journeyplus-daily.timer journeyplus-retry.timer
```

任务文件在 `.local/automation/runs/`，权限仅限运行用户。日志会替换已知 API 密钥、密码、OAuth token 和 Bearer 值；日志仍可能含业务资料，请保持 COS 私有。

## 发布与迁移

`entry.sh` 从待发布提交提取 `scripts/automation/`，健康检查通过后 `release.sh` 更新 `/opt/journeyplus-automation` 与 systemd 单元，不改变定时器启用状态。**已有服务器的 forced-command 入口需先由管理员更新一次 entry.sh**，后续才能自动提取新脚本。

换 CVM：停旧任务/写入，完成最终备份；新机安装 Docker、恢复数据库和凭据、绑定角色，执行 install.sh、验收后启用。配置路径通过安装参数传入；改云厂商需要更换 CVM 凭据获取方式。

COS 仅存储备份，不运行 PostgreSQL。日志上传不是主动消息通知，目前没有邮件/桌面告警渠道。

## 2026-09-18 验收记录

- 相关回归共 41 项通过，其中本地新增测试覆盖八份轮换、候选/归档/晋升失败、重复及乱序重传、未知备份保护、手工文件保护、业务失败判定、日志脱敏、导出失败仅上传日志，以及重试不调用 workflow。
- 已在测试 CVM 安装单元及脚本，定时器保持 disabled；systemd 解析的下一次时间为 2026-09-19 13:00:00 Asia/Shanghai。
- 一次真实 backup-only 已上传 COS 并完成回读校验；从 COS 下载的文件已恢复到临时验收数据库，账号 1、会籍 2、简报 26、文档版本 36，与原数据库一致。临时数据库已删除，原服务仍 healthy。
- 未执行完整 AIWorkflow：服务器尚缺 Gmail OAuth 客户端和 token 文件。未消耗模型配额，未启用每日调度，未提交或推送代码。
- 测试服务器的 GitHub forced-command 入口已更新，并通过 DEPLOY_CONNECTION_OK 检查；后续发布可携带 automation 脚本。应用没有重启。
