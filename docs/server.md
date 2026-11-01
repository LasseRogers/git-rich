# Running on a server

git-rich runs unattended on an Oracle Cloud Always Free Arm instance (`VM.Standard.A1.Flex`, 2 OCPUs and 12 GB, Ubuntu 24.04). Any Linux host with Docker works; the images build for both x86 and Arm.

## Preparing the host

On a fresh Ubuntu host, clone the repository and run the setup script as the user that will run git-rich:

```bash
git clone https://github.com/LasseRogers/git-rich.git && cd git-rich
./scripts/setup-server.sh
```

It sets the time zone the timers follow (`Europe/Copenhagen`, or pass another), installs Docker with Compose and the OCI CLI for [backups](backup.md), and lets the timers run while nobody is logged in. It skips whatever is already in place, so rerunning it is harmless. Log out and back in afterwards if it says so, so that `docker` works without `sudo`.

## Moving an existing setup

The paper bets, MLflow runs and model registry exist only on the old machine. Dump them there:

```bash
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc --no-owner --no-acl "$POSTGRES_DB"' > git-rich-db.dump
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc --no-owner --no-acl mlflow' > git-rich-mlflow.dump
docker run --rm -v git-rich_mlflow_artifacts:/a:ro -v "$PWD":/out alpine tar czf /out/git-rich-artifacts.tgz -C /a .
```

The database user follows `$USER`, which usually differs between machines, hence `--no-owner`. Copy the three files, `.env` and the Google key to the server, keep the key outside the repository, and point `GOOGLE_CREDENTIALS` at it. Then, from the directory holding them and the clone:

```bash
cd git-rich
git worktree add data/odds odds-data
docker compose build && docker compose create
docker run --rm -v git-rich_mlflow_artifacts:/a -v "$OLDPWD":/in:ro alpine tar xzf /in/git-rich-artifacts.tgz -C /a
docker compose up -d postgres
until docker compose logs postgres | grep -q "init process complete"; do sleep 2; done
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl' < "$OLDPWD/git-rich-db.dump"
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d mlflow --no-owner --no-acl' < "$OLDPWD/git-rich-mlflow.dump"
docker compose up -d
./scripts/install-timer.sh
```

Postgres runs its first-start setup before accepting the restore, hence the wait on its log.

## Access

Every port is bound to `127.0.0.1`, so nothing is reachable from the internet. Tunnel over SSH to use the panel, MLflow and the API from another machine:

```bash
ssh -L 8501:localhost:8501 -L 5050:localhost:5050 -L 8000:localhost:8000 ubuntu@<server>
```

The panel is then at http://localhost:8501, MLflow at http://localhost:5050 and the API at http://localhost:8000, or whichever ports `.env` sets.

The server is the only copy of the paper bets and MLflow history, so set up [weekly backups](backup.md).
