import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import lightgbm as lgb
import mlflow
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from gitrich.models import metrics

log = logging.getLogger(__name__)

MODEL_NAME = "lol-series"
CHAMPION = "champion"
# Retraining with the same code reproduces the champion's walk-forward predictions up to float noise.
TOLERANCE = 0.001


@dataclass
class LoadedModel:
    booster: lgb.Booster
    columns: list[str]
    k_league: float
    version: str
    run_id: str


def save(booster: lgb.Booster, columns: list[str], k_league: float, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(path / "model.txt"))
    (path / "meta.json").write_text(json.dumps({"columns": columns, "k_league": k_league}))


def register(run_id: str, test: pd.DataFrame) -> tuple[str, bool]:
    """Registers the run's model and promotes it unless it predicts the champion's test matches worse.

    Comparing on shared matches keeps a model retrained with newer seasons from being judged against
    a test set the champion never saw.
    """
    client = MlflowClient()
    try:
        client.create_registered_model(MODEL_NAME)
    except MlflowException:
        pass

    source = f"{client.get_run(run_id).info.artifact_uri}/model"
    version = client.create_model_version(MODEL_NAME, source=source, run_id=run_id).version

    champion = _champion(client)
    promote = champion is None or _at_least_as_good(test, champion.run_id)
    if promote:
        client.set_registered_model_alias(MODEL_NAME, CHAMPION, version)
    return version, promote


def latest_age() -> timedelta | None:
    """How long ago the newest version was registered, promoted or not."""
    versions = MlflowClient().search_model_versions(f"name = '{MODEL_NAME}'")
    if not versions:
        return None
    newest = max(v.creation_timestamp for v in versions)
    return datetime.now(timezone.utc) - datetime.fromtimestamp(newest / 1000, timezone.utc)


def load_champion() -> LoadedModel | None:
    champion = _champion(MlflowClient())
    if champion is None:
        return None
    path = Path(mlflow.artifacts.download_artifacts(artifact_uri=f"models:/{MODEL_NAME}@{CHAMPION}"))
    meta = json.loads((path / "meta.json").read_text())
    return LoadedModel(
        booster=lgb.Booster(model_file=str(path / "model.txt")),
        columns=meta["columns"],
        k_league=meta["k_league"],
        version=champion.version,
        run_id=champion.run_id,
    )


def _at_least_as_good(test: pd.DataFrame, champion_run: str) -> bool:
    path = mlflow.artifacts.download_artifacts(run_id=champion_run, artifact_path="series_predictions.parquet")
    champion = pd.read_parquet(path)[["match_id", "p_team1"]]
    shared = test.merge(champion, on="match_id", suffixes=("", "_champion"))
    if shared.empty:
        log.warning("no test matches in common with the champion, keeping it")
        return False
    new = metrics.log_loss(shared.team1_won, shared.p_team1)
    old = metrics.log_loss(shared.team1_won, shared.p_team1_champion)
    gain, low, high = metrics.gain(shared.team1_won, shared.p_team1_champion, shared.p_team1)
    mlflow.log_metrics({"champion_shared_n": len(shared), "champion_gain": gain,
                        "champion_gain_low": low, "champion_gain_high": high})
    log.info("%d shared test matches: log loss %.4f vs champion %.4f (gain %.4f, 95%% interval %.4f to %.4f)",
             len(shared), new, old, gain, low, high)
    return new <= old + TOLERANCE


def _champion(client: MlflowClient):
    try:
        return client.get_model_version_by_alias(MODEL_NAME, CHAMPION)
    except MlflowException:
        return None
