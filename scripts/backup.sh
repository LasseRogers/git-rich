#!/usr/bin/env bash
# Backs up what can't be fetched again to OCI Object Storage and keeps the newest few. See docs/backup.md.
set -Eeuo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/settings.sh
source scripts/settings.sh

KEEP=4
trap 'alert_failure "git-rich backup failed" "Details: journalctl --user -u git-rich-backup"' ERR

bucket=$(env_value BACKUP_BUCKET)
if [[ -z $bucket ]]; then
    echo "BACKUP_BUCKET is not set in .env" >&2
    exit 1
fi
oci=$(command -v oci || echo "$HOME/.local/bin/oci")

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir "$work/backup"

docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc --no-owner --no-acl "$POSTGRES_DB"' \
    > "$work/backup/db.dump"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc --no-owner --no-acl mlflow' \
    > "$work/backup/mlflow.dump"
docker run --rm -v git-rich_mlflow_artifacts:/a:ro alpine tar czf - -C /a . > "$work/backup/artifacts.tgz"
cp .env "$work/backup/env"
credentials=$(env_value GOOGLE_CREDENTIALS)
if [[ -n $credentials ]]; then
    cp "$credentials" "$work/backup/google-credentials.json"
fi

name="git-rich-$(date +%Y-%m-%dT%H%M).tar"
tar cf "$work/$name" -C "$work/backup" .

# The instance signs its own requests, so no API key lives on the server.
region=$(curl -fsS -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/instance/canonicalRegionName)
storage() {
    "$oci" os "$@" --auth instance_principal --region "$region"
}
namespace=$(storage ns get --query data --raw-output)
storage object put --namespace "$namespace" --bucket-name "$bucket" --name "$name" --file "$work/$name" --no-overwrite

# Names sort by date, so everything before the newest KEEP is older.
listing=$(storage object list --namespace "$namespace" --bucket-name "$bucket" --prefix git-rich- --all \
    --query "join(' ', data[].name)" --raw-output)
read -ra names <<< "$listing"
mapfile -t names < <(printf '%s\n' "${names[@]}" | sort)
if (( ${#names[@]} > KEEP )); then
    for old in "${names[@]:0:${#names[@]}-KEEP}"; do
        storage object delete --namespace "$namespace" --bucket-name "$bucket" --object-name "$old" --force
    done
fi
echo "uploaded $name ($(du -h "$work/$name" | cut -f1)), keeping the newest $KEEP"
