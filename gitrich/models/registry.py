import json
import logging
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import mlflow
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

log = logging.getLogger(__name__)

MODEL_NAME = "lol-series"
CHAMPION = "champion"


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


def register(run_id: str, test_log_loss: float) -> tuple[str, bool]:
    """Registers the run's model and promotes it if it beats the current champion on test log loss."""
    client = MlflowClient()
    try:
        client.create_registered_model(MODEL_NAME)
    except MlflowException:
        pass

    source = f"{client.get_run(run_id).info.artifact_uri}/model"
    version = client.create_model_version(MODEL_NAME, source=source, run_id=run_id).version

    champion = _champion(client)
    best = client.get_run(champion.run_id).data.metrics.get("test_log_loss") if champion else None
    promote = best is None or test_log_loss < best
    if promote:
        client.set_registered_model_alias(MODEL_NAME, CHAMPION, version)
    return version, promote


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


def _champion(client: MlflowClient):
    try:
        return client.get_model_version_by_alias(MODEL_NAME, CHAMPION)
    except MlflowException:
        return None
