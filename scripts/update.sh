#!/usr/bin/env bash
# Brings odds, paper bets and match data up to date. Run by hand, or by the git-rich-update timer.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

exec 9>"${XDG_RUNTIME_DIR:-/tmp}/git-rich-update.lock"
if ! flock -n 9; then
    echo "an update is already running"
    exit 0
fi

failed=()

step() {
    local name=$1
    shift
    echo "== $name"
    if ! "$@"; then
        echo "!! $name failed" >&2
        failed+=("$name")
    fi
}

run_job() {
    # No TTY, so it also runs unattended.
    docker compose --profile jobs run --rm -T "$@"
}

api() {
    echo "http://$(docker compose port api 8000)$1"
}

wait_for_api() {
    # The API replays every game on startup, and paper bets need it ready.
    for _ in $(seq 60); do
        curl -fsS "$(api /health)" 2>/dev/null | grep -q '"ready":true' && return 0
        sleep 5
    done
    return 1
}

pull_odds() {
    # Over HTTPS, since the repository is public and an unattended run may not have the SSH key unlocked.
    local url
    url=$(git remote get-url origin | sed -E 's#^git@github\.com:#https://github.com/#')
    git -C data/odds pull --quiet --ff-only "$url" odds-data
}

notify() {
    # Best effort: there's no desktop to notify on a server.
    command -v notify-send >/dev/null && notify-send --app-name=git-rich "$@" 2>/dev/null
    return 0
}

env_value() {
    sed -n "s/^$1=//p" .env 2>/dev/null | tail -n 1
}

alert_failure() {
    # The same ntfy.sh topic the Python jobs use; see docs/alerts.md.
    local topic
    topic=$(env_value NTFY_TOPIC)
    [[ -n $topic && $(env_value ALERT_FAILURES) != false ]] || return 0
    curl -fsS --max-time 10 -H "Title: git-rich update failed" -H "Priority: high" -H "Tags: warning" \
        -d "$1" "https://ntfy.sh/$topic" >/dev/null || true
}

step "start services" docker compose up -d
step "wait for the API" wait_for_api
# Odds before results, so paper bets are decided without seeing them.
step "pull odds" pull_odds
step "load odds and place paper bets" run_job ingest-odds
step "load match data" run_job ingest
# Monthly, so the model keeps learning from new seasons without anyone retraining it.
step "retrain the model" run_job train-lgbm --name scheduled --if-older-than 30
step "reload the API" curl -fsS -X POST --max-time 900 -o /dev/null "$(api /reload)"
# Settles bets on matches whose results just arrived. The first run already reported unmapped teams.
step "settle bets" run_job -e ALERT_UNMAPPED_TEAMS=false ingest-odds

if (( ${#failed[@]} )); then
    summary=$(printf '%s, ' "${failed[@]}")
    notify --urgency=critical "git-rich update failed" "${summary%, }"
    alert_failure "Failed: ${summary%, }. Details: journalctl --user -u git-rich-update"
    exit 1
fi
notify "git-rich updated" "Odds, paper bets and match data are up to date."
