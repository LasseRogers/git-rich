#!/usr/bin/env bash
# Runs one of the read-only queries in sql/ against the database container.
# Usage: scripts/query.sh <name> [argument]    Without a name it lists the queries.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ $# -eq 0 ]]; then
    for file in sql/*.sql; do
        printf '%-12s %s\n' "$(basename "$file" .sql)" "$(head -1 "$file" | sed 's/^-- //')"
    done
    exit 0
fi

file=sql/$1.sql
[[ -r $file ]] || { echo "no query $1; run $0 without arguments for the list" >&2; exit 1; }

# The session is read-only, so a query here can never change data.
docker compose exec -T -e PGOPTIONS="-c default_transaction_read_only=on" postgres \
    sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -q -v ON_ERROR_STOP=1 -v arg="$1"' _ "${2:-}" < "$file"
