#!/usr/bin/env bash
# 发布后手动查看日志、运行任务时使用当前发布版本，避免误用旧 local 镜像。
set -Eeuo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
state="$root/.local/deploy"
manifest="$root/compose.deploy.yaml"
if [[ -f "$state/current-image" && -f "$state/current-compose.yaml" ]]; then
  export JOURNEYPLUS_APP_IMAGE
  JOURNEYPLUS_APP_IMAGE=$(cat "$state/current-image")
  manifest="$state/current-compose.yaml"
fi
exec docker compose --project-directory "$root" --env-file "$root/.env.deploy" -f "$manifest" "$@"
