# shellcheck shell=bash
# Sourced by the scripts: reads .env and sends failure alerts. Run from the repository root.

env_value() {
    sed -n "s/^$1=//p" .env 2>/dev/null | tail -n 1
}

alert_failure() {
    # The same ntfy.sh topic the Python jobs use; see docs/alerts.md.
    local topic
    topic=$(env_value NTFY_TOPIC)
    [[ -n $topic && $(env_value ALERT_FAILURES) != false ]] || return 0
    curl -fsS --max-time 10 -H "Title: $1" -H "Priority: high" -H "Tags: warning" \
        -d "$2" "https://ntfy.sh/$topic" >/dev/null || true
}
