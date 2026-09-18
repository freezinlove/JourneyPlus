#!/usr/bin/env bash
# Install/update units without enabling daily execution implicitly.
set -Eeuo pipefail
root=${1:-$(cd "$(dirname "$0")/../.." && pwd)}
[[ $EUID == 0 ]] || { echo '请使用 sudo 执行。'; exit 1; }
[[ $root =~ ^/[A-Za-z0-9_./-]+$ ]] || { echo '项目路径不能包含空格或特殊字符。'; exit 1; }
install -d -m 700 /etc/journeyplus
if [[ ! -f /etc/journeyplus/backup.env ]]; then
  cat > /etc/journeyplus/backup.env <<'ENV'
COS_BUCKET=journeyplus-backups-1395705638
COS_REGION=ap-seoul
COS_ROLE=JourneyPlusBackupRole
ENV
  chmod 600 /etc/journeyplus/backup.env
fi
install -d -m 755 /opt/journeyplus-automation
install -m 755 "$(dirname "$0")/daily.py" /opt/journeyplus-automation/daily.py
for mode in daily retry; do
  cat > "/etc/systemd/system/journeyplus-${mode}.service" <<UNIT
[Unit]
Description=JourneyPlus ${mode}
Wants=network-online.target
After=network-online.target docker.service
Requires=docker.service
StartLimitIntervalSec=0
[Service]
Type=oneshot
EnvironmentFile=/etc/journeyplus/backup.env
ExecStart=/usr/bin/python3 /opt/journeyplus-automation/daily.py ${mode} --root ${root}
UMask=0077
TimeoutStartSec=infinity
Restart=on-failure
RestartSec=60
RestartPreventExitStatus=1
UNIT
done
cat > /etc/systemd/system/journeyplus-daily.timer <<'UNIT'
[Unit]
Description=JourneyPlus daily at 13:00 Asia/Shanghai
[Timer]
OnCalendar=*-*-* 13:00:00 Asia/Shanghai
Persistent=true
AccuracySec=1min
[Install]
WantedBy=timers.target
UNIT
cat > /etc/systemd/system/journeyplus-retry.timer <<'UNIT'
[Unit]
Description=Retry pending COS backups (never rerun AIWorkflow)
[Timer]
OnCalendar=*:0/30
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
echo '安装完成。尚未主动启用定时器；请先验收，再 enable --now。'
