"""Evaluation logged the same way for every model, so runs compare side by side in MLflow."""
import time

import mlflow
import pandas as pd
from mlflow import MlflowClient
from mlflow.entities import Metric

from gitrich.models import metrics

# MLflow accepts at most this many metric values per request.
BATCH = 1000


def log_test(test: pd.DataFrame, elo: str | None = "p_elo") -> None:
    """Test metrics for the active run. Per-season log loss is logged with the season as the step,
    so MLflow draws it as a line. `elo` names the column with Elo's predictions, if there is one."""
    y = test.team1_won
    scores = {f"test_{k}": v for k, v in {**metrics.summary(y, test.p_team1), **metrics.breakdown(test)}.items()}
    seasons = test.groupby("year")
    log_steps("season_log_loss", {year: metrics.log_loss(g.team1_won, g.p_team1) for year, g in seasons})
    if elo:
        scores["test_elo_log_loss"] = metrics.log_loss(y, test[elo])
        scores.update(zip(("elo_gain", "elo_gain_low", "elo_gain_high"), metrics.gain(y, test[elo], test.p_team1)))
        log_steps("season_elo_log_loss", {year: metrics.log_loss(g.team1_won, g[elo]) for year, g in seasons})
    mlflow.log_metrics(scores)


def log_steps(key: str, values: dict[int, float]) -> None:
    run_id = mlflow.active_run().info.run_id
    now = int(time.time() * 1000)
    points = [Metric(key, float(v), now, int(step)) for step, v in values.items()]
    client = MlflowClient()
    for i in range(0, len(points), BATCH):
        client.log_batch(run_id, metrics=points[i:i + BATCH])
