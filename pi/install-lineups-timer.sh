#!/usr/bin/env bash
# Runs pi/fetch_lineups.py every 30 minutes through a systemd user timer, with lingering so it keeps
# running while nobody is logged in.
# Usage: pi/install-lineups-timer.sh user@server [ssh key, default ~/.ssh/git_rich_lineups]
set -euo pipefail

server=${1:?usage: $0 user@server [ssh key]}
key=${2:-$HOME/.ssh/git_rich_lineups}
repo=$(cd "$(dirname "$0")/.." && pwd)
units=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user

[[ -r $key ]] || { echo "no SSH key at $key" >&2; exit 1; }
command -v rsync >/dev/null || { echo "rsync is missing: sudo apt-get install rsync" >&2; exit 1; }

mkdir -p "$units"
cat > "$units/git-rich-lineups.service" <<EOF
[Unit]
Description=Snapshot RotoWire LoL lineups and send changes to the git-rich server
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $repo/pi/fetch_lineups.py --server $server --key $key
# Stays out of the way of anything else the Pi runs.
Nice=10
EOF

cat > "$units/git-rich-lineups.timer" <<EOF
[Unit]
Description=Snapshot RotoWire LoL lineups every 30 minutes

[Timer]
OnCalendar=*:00/30
# Spreads requests away from the full and half hour, when everyone else's jobs fire.
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
EOF

loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now git-rich-lineups.timer
systemctl --user list-timers git-rich-lineups.timer --no-pager
