#!/usr/bin/env bash
# Schedules scripts/update.sh on Monday, Wednesday and Friday evenings, and scripts/backup.sh weekly
# once BACKUP_BUCKET is set, through systemd user timers.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
units=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
mkdir -p "$units"

timer() {
    local name=$1 description=$2 script=$3 calendar=$4
    cat > "$units/$name.service" <<EOF
[Unit]
Description=$description

[Service]
Type=oneshot
ExecStart=$repo/scripts/$script
EOF
    # Persistent catches up on a run missed while the machine was off.
    cat > "$units/$name.timer" <<EOF
[Unit]
Description=$description

[Timer]
OnCalendar=$calendar
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

timer git-rich-update "Update git-rich odds, paper bets and match data" update.sh "Mon,Wed,Fri 18:00"
timers=(git-rich-update.timer)
if grep -q '^BACKUP_BUCKET=.' "$repo/.env" 2>/dev/null; then
    timer git-rich-backup "Back up git-rich to Object Storage" backup.sh "Sun 03:00"
    timers+=(git-rich-backup.timer)
fi

# Lets the timers run without anyone logged in, as on a server.
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now "${timers[@]}"
systemctl --user list-timers "${timers[@]}"
