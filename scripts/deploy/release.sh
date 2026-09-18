#!/usr/bin/env bash
# 从 entry.sh 执行。stdin 仅接收本次 Actions 临时 GHCR token，不写入长期配置。
set -Eeuo pipefail
umask 077
revision=${1:?提交编号缺失}
image=${2:?镜像摘要缺失}
root=${3:?项目目录缺失}
manifest=${4:?Compose 文件缺失}
[[ $revision =~ ^[0-9a-f]{40}$ ]] || exit 64
[[ $image =~ ^ghcr\.io/freezinlove/journeyplus@sha256:[0-9a-f]{64}$ ]] || exit 64
cd "$root"
test -f .env.deploy && test -d .secrets
state="$root/.local/deploy"
mkdir -p "$state/backups"
exec 8> "$state/release.lock"
flock -w 900 8 || exit 75

registry_config=$(mktemp -d)
trap 'rm -rf "$registry_config"' EXIT
compose=(docker compose --project-directory "$root" --env-file "$root/.env.deploy" -f "$manifest")
export JOURNEYPLUS_APP_IMAGE="$image"
"${compose[@]}" config --quiet
available=$(df -Pk "$root" | awk 'NR==2 {print $4}')
(( available >= 1048576 )) || { echo '磁盘剩余不足 1 GiB，停止发布。' >&2; exit 1; }

echo '阶段：下载并核对镜像（现有服务继续运行）'
if ! docker --config "$registry_config" login ghcr.io -u freezinlove --password-stdin >/dev/null 2>&1; then
  echo 'GHCR 登录失败，未修改现有服务。' >&2
  exit 1
fi
docker --config "$registry_config" pull "$image"
label=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
[[ $label == "$revision" ]] || { echo '镜像提交标签不一致。' >&2; exit 1; }
docker run --rm --network none --entrypoint python "$image" -c \
  "from pathlib import Path; import journeyplus.cli; assert Path('/app/clients/web/dist/index.html').is_file(); assert Path('/app/alembic.ini').is_file()"
old_container=$("${compose[@]}" ps -q app)
[[ -n $old_container ]] || { echo '当前应用不存在；请先完成首次手动部署。' >&2; exit 1; }
old_image=$(docker inspect --format '{{.Image}}' "$old_container")
db_container=$("${compose[@]}" ps -q postgres)
[[ -n $db_container ]] && [[ $(docker inspect --format '{{.State.Health.Status}}' "$db_container") == healthy ]]
db_version() {
  "${compose[@]}" exec -T postgres psql -U journeyplus -d journeyplus -v ON_ERROR_STOP=1 -Atc \
    'SELECT version_num FROM alembic_version ORDER BY version_num'
}
before=$(db_version)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$state/backups/${stamp}-${revision}.dump"
phase=before-stop
old_manifest="$manifest"
if [[ -f "$state/current-compose.yaml" ]]; then old_manifest="$state/current-compose.yaml"; fi
recover() {
  code=$?
  trap - ERR
  set +e
  echo "发布失败，阶段：${phase}；备份：$backup" >&2
  if [[ $phase == stopped || $phase == backed-up || $phase == starting-unchanged ]]; then
    echo '数据库结构尚未改变，尝试恢复上一应用镜像。' >&2
    JOURNEYPLUS_APP_IMAGE="$old_image" docker compose --project-directory "$root" \
      --env-file "$root/.env.deploy" -f "$old_manifest" up -d --no-deps --no-build --wait --wait-timeout 180 app
    restored=$?
    if (( restored == 0 )); then echo '上一应用已恢复。' >&2; else echo '上一应用恢复失败，需要人工处理。' >&2; fi
  elif [[ $phase == migrating || $phase == starting-changed ]]; then
    "${compose[@]}" stop app
    echo '数据库迁移已开始或结构已改变，应用保持停止；不自动恢复数据库，请人工检查。' >&2
  fi
  exit "$code"
}
trap recover ERR
trap 'exit 130' INT
trap 'exit 143' TERM HUP

echo '阶段：暂停应用并备份数据库'
phase=stopped
"${compose[@]}" stop app
"${compose[@]}" exec -T postgres pg_dump -U journeyplus -d journeyplus \
  --format=custom --no-owner --no-acl > "$backup.partial"
"${compose[@]}" exec -T postgres pg_restore --list < "$backup.partial" >/dev/null
mv "$backup.partial" "$backup"
sha256sum "$backup" > "$backup.sha256"
phase=backed-up
printf '%s\n' "$old_image" > "$state/previous-image"
printf '%s\n' "$before" > "$state/previous-db-version"

echo '阶段：执行数据库迁移'
phase=migrating
"${compose[@]}" run --rm --no-deps --entrypoint alembic app upgrade head
after=$(db_version)
if [[ $before == "$after" ]]; then phase=starting-unchanged; else phase=starting-changed; fi
echo '阶段：启动并检查新应用'
"${compose[@]}" up -d --no-deps --no-build --wait --wait-timeout 180 app
"${compose[@]}" exec -T app python -c '
import urllib.request, urllib.error
assert urllib.request.urlopen("http://127.0.0.1:8000/login", timeout=10).status == 200
try:
    urllib.request.urlopen("http://127.0.0.1:8000/auth/me", timeout=10)
except urllib.error.HTTPError as exc:
    assert exc.code == 401
else:
    raise SystemExit("Unauthenticated API was not rejected")
'
# 后续手动管理需要同一版本的配置与镜像；不修改 .env.deploy 中的凭证。
cp "$manifest" "$state/current-compose.yaml.tmp"
mv "$state/current-compose.yaml.tmp" "$state/current-compose.yaml"
printf '%s\n' "$image" > "$state/current-image.tmp"
mv "$state/current-image.tmp" "$state/current-image"
printf '%s\n' "$revision" > "$state/current-revision"
printf '%s\n' "$after" > "$state/current-db-version"
echo "发布成功：$revision"
echo "备份路径：${backup}（服务器本机副本，不是异机备份）"
