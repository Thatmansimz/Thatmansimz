#!/bin/bash
# Run as root on the dedicated new VM only. Never starts a worker or imports keys.
set -euo pipefail
[[ $(id -u) = 0 ]] || { echo 'Run with sudo'; exit 1; }
[[ ! -e /etc/tajari/host-prepared ]] || { echo 'Host already prepared; inspect before repeating'; exit 1; }
[[ ! -e /opt/tajari/current ]] || { echo 'Existing installation found; refusing to overwrite'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv ca-certificates curl
id tajari >/dev/null 2>&1 || useradd --system --home-dir /var/lib/tajari --shell /usr/sbin/nologin tajari
install -d -o root -g root -m 0755 /opt/tajari/releases /opt/tajari/operations
install -d -o root -g tajari -m 0750 /etc/tajari
device=/dev/disk/by-id/google-tajari-paper-data
[[ -b "$device" ]] || { echo 'Expected dedicated data disk missing'; exit 1; }
[[ -z $(lsblk -no MOUNTPOINT "$device") ]] || { echo 'Data disk already mounted; inspect it'; exit 1; }
signature=$(blkid -s TYPE -o value "$device" || true)
if [[ -z "$signature" ]]; then
  # Never format a nonblank device or a disk with partitions/filesystem markers.
  [[ -z $(wipefs --no-act --noheadings "$device") ]] || { echo 'Nonblank disk; refusing format'; exit 1; }
  mkfs.ext4 -L tajari-paper-data "$device"
elif [[ "$signature" != ext4 ]]; then
  echo 'Unexpected existing filesystem; refusing format'; exit 1
fi
install -d -m 0755 /var/lib/tajari
uuid=$(blkid -s UUID -o value "$device")
[[ -n "$uuid" ]] || exit 1
# A missing data disk must prevent startup, not create an empty replacement run.
printf 'UUID=%s /var/lib/tajari ext4 defaults,nodev,nosuid 0 2\n' "$uuid" >> /etc/fstab
mount /var/lib/tajari
chown tajari:tajari /var/lib/tajari
chmod 0700 /var/lib/tajari
install -d -o tajari -g tajari -m 0700 /var/lib/tajari/runs /var/lib/tajari/backups
cat > /etc/systemd/system/tajari-paper.service <<'UNIT'
[Unit]
Description=Tajari registered streaming internal paper worker
Wants=network-online.target
After=network-online.target
RequiresMountsFor=/var/lib/tajari
ConditionPathExists=/etc/tajari/paper.env
ConditionPathExists=/var/lib/tajari/runs/mnq-forward-20260915/registration.json
ConditionPathExists=!/var/lib/tajari/runs/mnq-forward-20260915/STOP
ConditionPathExists=!/etc/tajari/maintenance-in-progress

[Service]
Type=simple
User=tajari
Group=tajari
WorkingDirectory=/opt/tajari/current
ExecStart=/opt/tajari/current/.venv-paper/bin/python /opt/tajari/current/scripts/continuous_paper.py run --run-dir /var/lib/tajari/runs/mnq-forward-20260915 --env-file /etc/tajari/paper.env --port 8022
Restart=on-failure
RestartSec=30
TimeoutStopSec=45
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
ReadWritePaths=/var/lib/tajari
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl disable tajari-paper.service
touch /etc/tajari/host-prepared
echo 'Host prepared. Service is disabled; no credentials, run or subscription installed.'
