# git-rich

Match outcome prediction for esports, compared against bookmaker odds.

## Stack

- Postgres for match, odds and prediction data
- MLflow for experiment tracking and the model registry
- Docker Compose to run everything locally

## Setup

```bash
cp .env.example .env    # set a password
docker compose up -d --build
```

The database user is taken from `$USER`. Avoid `@ : / #` in the password.

| Service  | Address                 |
|----------|-------------------------|
| MLflow   | http://localhost:5050   |
| Postgres | localhost:5432          |

Ports can be changed in `.env`.

## Commands

```bash
docker compose ps              # status
docker compose logs -f mlflow  # follow logs
docker compose down            # stop, keep data
docker compose down -v         # stop, delete data
```
