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
| Panel    | http://localhost:8501 |
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

Odds come from [OddsPapi](https://oddspapi.io). The `collect-odds` workflow snapshots LoL odds three times a day and commits them to the `odds-data` branch. GitHub's built-in schedule skipped and delayed runs, so the workflow is started through an external scheduler instead.

The free tier allows roughly 250 requests a month, so the workflow is budgeted around it: one request per bookmaker per run, and reference data refreshed at most daily. Requests are counted in `usage/` on the data branch and the collector stops at 220.

Setup:

- Add `ODDSPAPI_KEY` as a repository secret.
- Create the data branch once:
  ```bash
  git push origin "$(git commit-tree "$(git mktree </dev/null)" -m "Start odds data"):refs/heads/odds-data"
  ```
- Create a fine-grained token with access to this repository only and **Actions: Read and write**.
- Schedule two jobs on [cron-job.org](https://cron-job.org) (or any scheduler), in UTC:

  | Schedule | Body |
  |---|---|
  | `23 7,15 * * *` | `{"ref":"main","inputs":{"bookmakers":"pinnacle bet365"}}` |
  | `23 21 * * *` | `{"ref":"main","inputs":{"bookmakers":"pinnacle"}}` |

  Both `POST` to `https://api.github.com/repos/<owner>/<repo>/actions/workflows/collect-odds.yml/dispatches` with the headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28` and `Content-Type: application/json`. A successful trigger returns `204`.

When the token expires (GitHub emails a reminder), replace it in both jobs. GitHub announces the end of an API version through the `Deprecation` and `Sunset` headers on the response, visible in the scheduler's job history; bump `X-GitHub-Api-Version` before then.

To trigger a run manually:

```bash
gh workflow run collect-odds.yml -f bookmakers="pinnacle bet365"
```

Loading into Postgres, with the data branch checked out as a worktree under `data/odds`:

```bash
git worktree add data/odds odds-data    # once
git -C data/odds pull
docker compose run --rm ingest-odds
```

Prices are stored per capture, so the series of snapshots gives the line movement. A price captured after a match's `start_time` is in-play, regardless of the source's status field.

The import also maps OddsPapi teams to ours and links each odds event to its match in `core.matches` once Oracle's Elixir has the result. Teams are matched on normalized names among teams active in the last 400 days. Names that don't match are logged; map them in `gitrich/odds/team_aliases.csv` using the team name as it appears in `core.teams`. Aliases also override an incorrect automatic match.

### Backfilling history

OddsPapi keeps the price history of finished fixtures, currently from January 2026. The `collect-history` workflow fetches it for backtests into `history/` on the data branch, one request per fixture from the same monthly budget as `collect-odds`:

```bash
gh workflow run collect-history.yml -f max=200
```

It covers the major domestic leagues by default; pass `-f tournaments="..."` with OddsPapi tournament IDs to change them. Fixtures are fetched in a fixed shuffled order, so a partial backfill is a fair sample of the season, and fixtures already fetched are skipped, so the workflow can be rerun each month until the budget has covered them.

`ingest-odds` loads the winner market from these files, flagged as backfilled. Paper trading only acts on prices it saw live, so the backfill never places bets on matches already played.

## Models

Every model logs to the `lol-series` experiment in MLflow, tagged `model=elo`, `lgbm` or `logreg`, so runs can be compared side by side on test log loss.

### Elo baseline

```bash
docker compose run --rm train-elo
```

Walk-forward Elo on individual games: every prediction uses only earlier games. In `player` mode a team's rating is the mean of its five players, which carries strength across roster moves and rebrands; `team` mode is kept as a comparison. Series probabilities come from the per-game probability and the best-of format. The blue-side advantage is estimated walk-forward as well.

Parameters are tuned on 2019–2022 and reported on 2023 onwards, which is never used for tuning. Per-season metrics, calibration, series predictions and the final ratings are logged as run artifacts.

### Backtest

```bash
docker compose run --rm backtest                       # latest Elo run vs Pinnacle
docker compose run --rm backtest --model lgbm          # latest LightGBM run
docker compose run --rm backtest --bookmaker bet365 --threshold 0.05
```

Takes predictions from the latest run of `--model` (`elo` by default), or from a specific run with `--run`. Bets one unit on the side with the larger expected value when it exceeds the threshold, at the first (`--entry opening`) or last (`--entry closing`) pre-match price collected. Reports ROI, hit rate and closing line value against Pinnacle's margin-free closing price, plus the model's log loss next to the market's on the same matches. Results are logged to the `lol-backtest` experiment.

ROI needs hundreds of bets before it means much; CLV and the log loss comparison are the earlier signals.

### LightGBM

```bash
docker compose run --rm train-lgbm                          # all feature groups
docker compose run --rm train-lgbm --groups elo,league      # ablation
```

Gradient boosting on walk-forward pre-series features, grouped so groups can be switched on and off and compared:

| Group | Features |
|---|---|
| `elo` | player and team Elo difference, Elo series probability |
| `league` | region strength offset learned from cross-league games, cross-league flag |
| `roster` | player experience |
| `form` | recent win rate, rating momentum, gold difference at 15 minutes |
| `schedule` | rest days, games in the last week |
| `format` | best-of |

Each test season is predicted by a model trained on all earlier seasons except the last, which is used for early stopping. Features are built exactly as the API builds them before a match, from each team's previous lineup, so test scores reflect live predictions. Every series is seen from both sides during training and prediction, so team order carries no information. The run logs the Elo log loss on the same series for comparison, and its `series_predictions.parquet` works with `backtest --model lgbm`.

### Logistic regression

```bash
docker compose run --rm train-logreg
```

The LightGBM features in an L2-regularised logistic regression, with the same walk-forward seasons and training window, to measure what the trees add over a linear model. Standardised coefficients are logged per test season. The model isn't registered, so it never becomes the champion.

Features that describe the match rather than a team (`best_of`, `cross_league`) don't change sign when the teams are swapped, so a symmetric linear model gives them no weight. They can only matter through interactions with the difference features.

## Prediction API

`train-lgbm` refits the model on all seasons and registers it as `lol-series` in MLflow. A new version becomes the `champion` alias when its test log loss beats the current champion's. The API serves the champion; after training or loading new games, `POST /reload` picks up both.

| Endpoint | |
|---|---|
| `GET /health` | model version and how many games the feature state covers |
| `GET /upcoming?hours=72` | predictions for upcoming matches with mapped teams |
| `GET /predict?team1_id=&team2_id=` | any pairing, for each series format |
| `POST /paper-trade` | place paper bets on every match due a decision |
| `POST /reload` | reload the champion and replay all games |

Interactive docs are at `/docs`.

Lineups aren't known before a match, so each team's most recent lineup is assumed, in training as well. The format comes from the markets offered: a match with map 3 or map handicap markets is treated as a Bo3, otherwise a Bo1. Bo5s look identical to Bo3s in the odds, so `p_team1_by_format` returns all three.

`/upcoming` and `/paper-trade` store the first prediction per match and model version in `core.predictions`, which is the record paper trading is evaluated on.

## Paper trading

`ingest-odds` settles finished bets, then places new ones through `POST /paper-trade`.

Each match is decided as of 12 hours before its start, at prices captured in the 12 hours before that, so a late run catches up on missed matches without seeing the future. A match is skipped if either team has played since its decision time, so load odds before match data.

A match gets at most one bet, at the best available price, when:

- Pinnacle has a price, which closing line value is measured against
- both teams are from the same region; the model overrates weaker regions in international games
- the edge is between 3% and 15%; larger edges are almost always model errors

Every bet is a flat `STAKE` of 20 kr. The rules are in `gitrich/betting/strategy.py`.

CLV compares the price taken with Pinnacle's margin-free closing price, whichever bookmaker took the bet. It becomes meaningful long before profit does.

## Panel

http://localhost:8501 shows the bets to place on upcoming matches, and how the paper bets would have done with any amount per bet.
