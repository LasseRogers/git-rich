# Backups

`scripts/backup.sh` keeps what can't be fetched again in OCI Object Storage: the database (paper bets, predictions, odds and matches), the MLflow database and artifacts (runs, the model registry and model files), `.env` and the Google key. Code, odds and match data are on GitHub and Google Drive anyway, but restoring from one file is quicker than reloading them.

Each run uploads one `git-rich-<date>.tar` of about 550 MB and deletes all but the newest four, well inside the Always Free 20 GB. A failed run sends a [phone alert](alerts.md).

## Setup

The server authenticates as itself (an instance principal), so no API key is stored on it. In the OCI console:

1. **Bucket:** Storage → Buckets → Create bucket, named `git-rich-backups`, Standard tier, private.
2. **Dynamic group:** Identity & Security → Domains → Default → Dynamic groups → Create, named `git-rich-server`, with the rule `instance.id = '<the instance OCID>'`.
3. **Policy:** Identity & Security → Policies → Create, in the root compartment:

   ```
   Allow dynamic-group git-rich-server to read objectstorage-namespaces in tenancy
   Allow dynamic-group git-rich-server to manage objects in tenancy where target.bucket.name = 'git-rich-backups'
   ```

On the server, check that the instance can sign in with the OCI CLI, which `scripts/setup-server.sh` installs:

```bash
~/.local/bin/oci os ns get --auth instance_principal
```

Then set `BACKUP_BUCKET=git-rich-backups` in `.env`, run `./scripts/backup.sh` once, and rerun `./scripts/install-timer.sh`, which adds a timer for Sunday at 03:00 once the bucket is set.

## Restoring

Download a backup from the bucket in the console, or with `oci os object get`, and unpack it:

```bash
mkdir restore && tar xf git-rich-<date>.tar -C restore
```

It holds `db.dump`, `mlflow.dump`, `artifacts.tgz`, `env` and `google-credentials.json`, the same files the [server move](server.md#moving-an-existing-setup) uses, so restore them the same way.
