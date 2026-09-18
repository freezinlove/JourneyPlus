#!/usr/bin/env bash
# 安装到 /usr/local/bin/journeyplus-deploy-entry，作为部署公钥的 forced command。
set -Eeuo pipefail
umask 077
ROOT=/home/ubuntu/JourneyPlus
REPOSITORY=ghcr.io/freezinlove/journeyplus

if [[ ${SSH_ORIGINAL_COMMAND:-} == check ]]; then
  test -d "$ROOT/.git"
  test -f "$ROOT/.env.deploy"
  sudo -n true
  printf 'DEPLOY_CONNECTION_OK\n'
  exit 0
fi
read -r operation revision image extra <<< "${SSH_ORIGINAL_COMMAND:-}"
[[ $operation == deploy && -z ${extra:-} && $revision =~ ^[0-9a-f]{40}$ ]] || exit 64
[[ $image =~ ^${REPOSITORY}@sha256:[0-9a-f]{64}$ ]] || exit 64

# 发布入口以 SSH 用户运行；备份与发布状态目录由 root 私有管理。
entry_state="$HOME/.cache/journeyplus-deploy"
mkdir -p "$entry_state/releases"
exec 9> "$entry_state/entry.lock"
flock -w 900 9 || exit 75
# 不 checkout、不覆盖服务器工作区，只读取 main 上的指定提交。
git -C "$ROOT" fetch --quiet origin main </dev/null
git -C "$ROOT" merge-base --is-ancestor "$revision" origin/main || exit 65
release=$(mktemp -d "$entry_state/releases/${revision}.XXXXXX")
paths=(compose.deploy.yaml scripts/deploy/release.sh)
if git -C "$ROOT" cat-file -e "$revision:scripts/automation/install.sh" 2>/dev/null; then
  paths+=(scripts/automation)
fi
git -C "$ROOT" archive "$revision" "${paths[@]}" |
  tar -x -C "$release"
sudo -n bash "$release/scripts/deploy/release.sh" "$revision" "$image" "$ROOT" "$release/compose.deploy.yaml"
