#!/usr/bin/env bash
# Prepares a fresh Ubuntu host to run git-rich: time zone, Docker with Compose, the OCI CLI for
# backups and lingering for the user timers. Safe to rerun; whatever is already in place is kept.
# Usage: scripts/setup-server.sh [time zone], defaulting to Europe/Copenhagen.
set -euo pipefail

timezone=${1:-Europe/Copenhagen}

if [[ $EUID -eq 0 ]]; then
    echo "Run this as the user that will run git-rich, not as root; it uses sudo where needed." >&2
    exit 1
fi
if ! command -v apt-get >/dev/null; then
    echo "This script supports Ubuntu and other apt-based hosts only." >&2
    exit 1
fi

step() { printf '\n==> %s\n' "$*"; }

# The update and backup timers fire at local times, so the host clock has to be in the right zone.
step "Time zone $timezone"
if [[ $(timedatectl show --property=Timezone --value) != "$timezone" ]]; then
    sudo timedatectl set-timezone "$timezone"
fi

step "Docker"
if docker compose version >/dev/null 2>&1; then
    echo "already installed: $(docker --version)"
else
    # Docker's own repository: Ubuntu's docker.io lags behind and lacks the buildx plugin that
    # docker compose build uses.
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    # shellcheck source=/dev/null
    codename=$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]" \
        "https://download.docker.com/linux/ubuntu $codename stable" |
        sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

relogin=false
if ! id -nG "$USER" | grep -qw docker; then
    sudo usermod -aG docker "$USER"
    relogin=true
fi

# Backups authenticate as the instance itself, so the CLI needs no configuration; see docs/backup.md.
step "OCI CLI"
if [[ -x $HOME/.local/bin/oci ]]; then
    echo "already installed: $("$HOME/.local/bin/oci" --version)"
else
    command -v pipx >/dev/null || { sudo apt-get update && sudo apt-get install -y pipx; }
    pipx install oci-cli
    pipx ensurepath >/dev/null
fi

# Keeps the user's systemd timers running while nobody is logged in.
step "Lingering for $USER"
sudo loginctl enable-linger "$USER"

step "Done"
if $relogin; then
    echo "Log out and back in so that docker runs without sudo."
fi
echo "Next: restore or create .env, then follow docs/server.md from 'docker compose build'."
