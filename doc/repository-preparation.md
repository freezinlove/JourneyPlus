# 本地仓库整理与 GitHub 上传边界

## 仓库内容

服务端、Web、Android 放在同一私有仓库，独立构建。保留源码、迁移、测试、金标、设计原型及截图、依赖锁文件和 Gradle Wrapper。

以下内容只留本机，不能靠 Git 部署或备份：

- `.env` 及环境变体、`.secrets/`、OAuth 凭证、签名密钥。
- `.local/`、数据库文件及数据库归档。
- 模型请求/响应追踪、运行日志、评测运行输出。
- 依赖安装目录、构建产物及开发工具缓存。

`.gitignore` 防止新增跟踪，`.dockerignore` 防止未来构建 Docker 镜像时发送这些文件。当前尚未配置应用 Docker 镜像或自动部署。

## 本次整理

187 份已跟踪的运行产物通过 `git rm --cached` 取消跟踪，文件仍保存在原路径。具体清单位于本机 `.local/repository-cleanup/removed-from-index.json`，该清单自身也不上传。

其中两个测试依赖已迁至 `tests/fixtures/legacy_workflow/`，分别是旧模型源码和不含业务数据的 schema-only SQL。测试与验证脚本已更新引用。

历史审计文档中的原始日志、数据库归档链接属于本机证据，新克隆不会包含这些内容；可复用的审计脚本与 Markdown 说明仍保留。`evaluation/runs/` 是生成输出，`gold/` 是保留的评测输入。

## 上传前检查

```bash
git status --short
git diff --check
git diff --cached --check
python3 scripts/audit_repository.py --history
uv run pytest tests/test_agent_workflow_reads.py -q
```

审计脚本只输出路径与类别，不输出密钥值。默认检查已跟踪文件的工作区内容、未忽略的新文件，以及仍被跟踪的忽略文件；`--history` 另外扫描所有可达历史 blob。它不会单独校验暂存版本，提交前应确保暂存内容与已检查内容一致。

这是常见令牌格式及本机 `.env` 长密钥的启发式检查，不覆盖所有密码格式、个人信息或图片内容，不能视为完整安全认证。

## 历史与后续步骤

本次没有创建提交、修改历史或推送。取消跟踪只影响下一份代码快照，旧提交仍包含运行资料和归档。直接推送现有分支会一并上传其历史。

首次上传前需决定：允许这些历史资料进入私有仓库，或另行清理历史/建立不含旧历史的发布仓库。后两种操作尚未执行，需要用户明确选择。数据库与凭证应另行安全迁移，不能重新加回 Git。

确认仓库上传边界后，再创建私有 GitHub 仓库、提交及推送；随后配置服务器、服务端环境变量、数据迁移、HTTPS 和发布流程。
