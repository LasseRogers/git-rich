# git-rich

Esports match prediction, benchmarked against bookmaker odds.

## Setup

```bash
cp .env.example .env
docker compose up -d --build
```

All Python services share the `git-rich-app` image, so this also updates the jobs.

The Postgres user is taken from `$USER`. The password is embedded in connection URLs, so avoid `@ : / #`.

| Service  | Address               |
|----------|-----------------------|
| MLflow   | http://localhost:5050 |
| API      | http://localhost:8000 |
| Postgres | localhost:5432        |

## Database

Schemas are managed with Alembic and applied by the `migrate` service on startup.

- `core`: teams, players, matches, odds, predictions, bets
- `lol`: League of Legends games and per-game stats

## Data

Match data comes from [Oracle's Elixir](https://oracleselixir.com/tools/downloads), one file per year, updated daily.

```bash
docker compose run --rm ingest 2024 2025 2026
```

Without arguments the current year is loaded. Loads are idempotent, so re-running a year picks up new games.

Series aren't part of the source data. They're reconstructed from consecutive games between the same teams, and `best_of` is inferred from the winning score.

## Odds

Odds come from [OddsPapi](https://oddspapi.io). The `collect-odds` workflow snapshots LoL odds three times a day and commits them to the `odds-data` branch, so collection doesn't depend on a local machine being on.

The free tier allows roughly 250 requests a month, so the workflow is budgeted around it: one request per bookmaker per run, and reference data refreshed at most daily. Requests are counted in `usage/` on the data branch and the collector stops at 220.

Setup:

- Add `ODDSPAPI_KEY` as a repository secret.
- Create the data branch once:
  ```bash
  git push origin "$(git commit-tree "$(git mktree </dev/null)" -m "Start odds data"):refs/heads/odds-data"
  ```

Loading into Postgres, with the data branch checked out as a worktree under `data/odds`:

```bash
git worktree add data/odds odds-data    # once
git -C data/odds pull
docker compose run --rm ingest-odds
```

Prices are stored per capture, so the series of snapshots gives the line movement. A price captured after a match's `start_time` is in-play, regardless of the source's status field.

The import also maps OddsPapi teams to ours and links each odds event to its match in `core.matches` once Oracle's Elixir has the result. Teams are matched on normalized names among teams active in the last 400 days. Names that don't match are logged; map them in `gitrich/odds/team_aliases.csv` using the team name as it appears in `core.teams`. Aliases also override an incorrect automatic match.

## Models

Experiments are tracked in MLflow under one experiment per model family.

### Elo baseline

```bash
docker compose run --rm train-elo
```

Walk-forward Elo on individual games: every prediction uses only earlier games. In `player` mode a team's rating is the mean of its five players, which carries strength across roster moves and rebrands; `team` mode is kept as a comparison. Series probabilities come from the per-game probability and the best-of format. The blue-side advantage is estimated walk-forward as well.

Parameters are tuned on 2019–2022 and reported on 2023 onwards, which is never used for tuning. Per-season metrics, calibration, series predictions and the final ratings are logged as run artifacts.

### Backtest

```bash
docker compose run --rm backtest                       # latest Elo run vs Pinnacle
docker compose run --rm backtest --bookmaker bet365 --threshold 0.05
```

Bets one unit on the side with the larger expected value when it exceeds the threshold, at the first (`--entry opening`) or last (`--entry closing`) pre-match price collected. Reports ROI, hit rate and closing line value against Pinnacle's margin-free closing price, plus the model's log loss next to the market's on the same matches. Results are logged to the `lol-backtest` experiment.

ROI needs hundreds of bets before it means much; CLV and the log loss comparison are the earlier signals.

### LightGBM

```bash
docker compose run --rm train-lgbm                          # all feature groups
docker compose run --rm train-lgbm --groups elo,league      # ablation
```

Gradient boosting on walk-forward pre-series features, grouped so groups can be switched on and off and compared in the `lol-series-lgbm` experiment:

| Group | Features |
|---|---|
| `elo` | player and team Elo difference, Elo series probability |
| `league` | region strength offset learned from cross-league games, cross-league flag |
| `roster` | player experience, players new since the team's previous game |
| `form` | recent win rate, rating momentum, gold difference at 15 minutes |
| `schedule` | rest days, games in the last week |
| `format` | best-of, playoffs |

Each test season is predicted by a model trained on all earlier seasons except the last, which is used for early stopping. Every series is seen from both sides during training and prediction, so team order carries no information. The run logs the Elo log loss on the same series for comparison, and its `series_predictions.parquet` works with `backtest --experiment lol-series-lgbm`.

## Prediction API

`train-lgbm` refits the model on all seasons and registers it as `lol-series` in MLflow. A new version becomes the `champion` alias when its test log loss beats the current champion's. The API serves the champion; after training or loading new games, `POST /reload` picks up both.

| Endpoint | |
|---|---|
| `GET /health` | model version and how many games the feature state covers |
| `GET /upcoming?hours=72` | predictions for upcoming matches with mapped teams |
| `GET /predict?team1_id=&team2_id=` | any pairing, for each series format |
| `POST /reload` | reload the champion and replay all games |

Interactive docs are at `/docs`.

Lineups aren't known before a match, so each team's most recent lineup is assumed. The format comes from the markets offered: a match with map 3 or map handicap markets is treated as a Bo3, otherwise a Bo1. Bo5s look identical to Bo3s in the odds, so `p_team1_by_format` returns all three.

`/upcoming` stores the first prediction per match and model version in `core.predictions`, which is the record paper trading is evaluated on.
