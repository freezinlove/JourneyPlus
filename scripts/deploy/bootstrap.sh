#!/usr/bin/env bash
# 一次性安装入口。以 ubuntu 执行，参数仅为部署公钥文件，不是私钥。
set -Eeuo pipefail
[[ $(id -un) == ubuntu ]] || { echo '请以 ubuntu 用户运行。' >&2; exit 1; }
public_key=${1:?请提供专用部署公钥文件路径}
[[ -f $public_key ]] || exit 1
key=$(cat "$public_key")
[[ $key =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ .*)?$ ]] || exit 1
sudo install -o root -g root -m 0755 "$(dirname "$0")/entry.sh" /usr/local/bin/journeyplus-deploy-entry
install -d -m 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
line="restrict,command=\"/usr/local/bin/journeyplus-deploy-entry\" $key"
if ! grep -Fqx "$line" "$HOME/.ssh/authorized_keys"; then
  printf '\n%s\n' "$line" >> "$HOME/.ssh/authorized_keys"
fi
echo '部署入口已安装；现有应用没有重启。'
