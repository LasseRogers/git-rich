#!/usr/bin/env bash
# Runs scripts/update.sh on Monday, Wednesday and Friday evenings through a systemd user timer.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
units=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
mkdir -p "$units"

cat > "$units/git-rich-update.service" <<EOF
[Unit]
Description=Update git-rich odds, paper bets and match data

[Service]
Type=oneshot
ExecStart=$repo/scripts/update.sh
EOF

# Persistent catches up on a run missed while the machine was off.
cat > "$units/git-rich-update.timer" <<EOF
[Unit]
Description=Update git-rich on Monday, Wednesday and Friday evenings

[Timer]
OnCalendar=Mon,Wed,Fri 18:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Lets the timer run without anyone logged in, as on a server.
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now git-rich-update.timer
systemctl --user list-timers git-rich-update.timer
