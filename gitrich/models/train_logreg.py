"""Walk-forward logistic regression on the LightGBM features, to measure what the trees add over a linear model."""
import argparse
import logging
import tempfile
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd

from gitrich.db import connect
from gitrich.lol.data import load_games, load_matches
from gitrich.models import features, metrics

log = logging.getLogger("train-logreg")

EXPERIMENT = "lol-series"


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


class LogisticModel:
    """L2-regularised logistic regression on standardised features, fitted by Newton's method."""

    def __init__(self, l2: float = 1.0):
        self.l2 = l2

    def fit(self, X: pd.DataFrame, y: np.ndarray, max_iter: int = 100) -> "LogisticModel":
        # Missing values become the training mean, which is zero for difference features on mirrored data.
        self.mean = X.mean().fillna(0.0)
        self.scale = X.std().replace(0.0, 1.0).fillna(1.0)
        Z = self._design(X)
        penalty = np.full(Z.shape[1], self.l2)
        penalty[0] = 0.0

        w = np.zeros(Z.shape[1])
        for _ in range(max_iter):
            p = _sigmoid(Z @ w)
            grad = Z.T @ (p - y) + penalty * w
            hess = (Z.T * (p * (1 - p))) @ Z + np.diag(penalty)
            step = np.linalg.solve(hess, grad)
            w -= step
            if np.abs(step).max() < 1e-8:
                break
        else:
            log.warning("Newton's method did not converge in %d iterations", max_iter)

        self.coef = pd.Series(w, index=["intercept", *X.columns])
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return _sigmoid(self._design(X) @ self.coef.to_numpy())

    def _design(self, X: pd.DataFrame) -> np.ndarray:
        Z = ((X.fillna(self.mean) - self.mean) / self.scale).to_numpy(dtype=float)
        return np.column_stack([np.ones(len(Z)), Z])


def both_sides(df: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    won = df.team1_won.to_numpy(dtype=bool)
    X = pd.concat([df[cols], features.flip(df[cols])], ignore_index=True)
    return X, np.concatenate([won, ~won]).astype(float)


def predict(model: LogisticModel, X: pd.DataFrame) -> np.ndarray:
    return (model.predict(X) + 1 - model.predict(features.flip(X))) / 2


def main() -> None:
    parser = argparse.ArgumentParser(prog="train-logreg", description="Walk-forward logistic regression baseline.")
    parser.add_argument("--groups", default=",".join(features.GROUPS),
                        help=f"feature groups, from: {', '.join(features.GROUPS)}")
    parser.add_argument("--train-from", type=int, default=2016)
    parser.add_argument("--test-from", type=int, default=2023)
    parser.add_argument("--k-league", type=float, default=16.0)
    parser.add_argument("--l2", type=float, default=1.0)
    parser.add_argument("--name", help="MLflow run name")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    groups = args.groups.split(",")
    cols = features.columns(groups)

    with connect() as conn:
        games = load_games(conn)
        matches = load_matches(conn)
    df = features.build(games, matches, k_league=args.k_league)
    df = df[df.year >= args.train_from]
    log.info("%d series with features", len(df))

    # Same training window as LightGBM, which holds out the previous season for early stopping,
    # so any difference comes from the model and not from fresher data.
    predictions, coefs = [], []
    for year in sorted(y for y in df.year.unique() if y >= args.test_from):
        train, test = df[df.year < year - 1], df[df.year == year]
        if train.empty:
            continue
        model = LogisticModel(args.l2).fit(*both_sides(train, cols))
        out = test[["match_id", "league", "year", "best_of", "team1_id", "team2_id", "team1_won"]].copy()
        out["p_team1"] = predict(model, test[cols])
        out["p_elo"] = _sigmoid(test.elo_series_logit.to_numpy())
        predictions.append(out)
        coefs.append(model.coef.rename(year))
        log.info("%d: log loss %.4f (elo %.4f)", year,
                 metrics.log_loss(out.team1_won, out.p_team1), metrics.log_loss(out.team1_won, out.p_elo))

    preds = pd.concat(predictions, ignore_index=True)
    by_year = pd.DataFrame({
        year: {"n": len(g), "log_loss": metrics.log_loss(g.team1_won, g.p_team1),
               "elo_log_loss": metrics.log_loss(g.team1_won, g.p_elo),
               "accuracy": metrics.accuracy(g.team1_won, g.p_team1)}
        for year, g in preds.groupby("year")
    }).T
    coef = pd.concat(coefs, axis=1)
    coef = coef.reindex(coef.drop("intercept").abs().mean(axis=1).sort_values(ascending=False).index.insert(0, "intercept"))
    test = preds[preds.groupby("year").year.transform("size") >= 200]
    calibration = metrics.calibration(test.team1_won, test.p_team1)

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=args.name or "+".join(groups)) as run:
        mlflow.set_tags({"predictions": "series", "model": "logreg"})
        mlflow.log_params({"groups": args.groups, "train_from": args.train_from, "test_from": args.test_from,
                           "k_league": args.k_league, "l2": args.l2})
        mlflow.log_metrics({f"test_{k}": v for k, v in metrics.summary(test.team1_won, test.p_team1).items()})
        mlflow.log_metric("test_elo_log_loss", metrics.log_loss(test.team1_won, test.p_elo))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            preds.drop(columns="p_elo").to_parquet(tmp / "series_predictions.parquet", index=False)
            by_year.to_csv(tmp / "by_year.csv", index_label="year")
            coef.to_csv(tmp / "coefficients.csv", index_label="feature")
            calibration.to_csv(tmp / "calibration_test.csv", index_label="bucket")
            mlflow.log_artifacts(str(tmp))

    print(f"\nRun: {run.info.run_id}   groups: {args.groups}\n")
    print(by_year.round(4).to_string())
    print(f"\nTest log loss {metrics.log_loss(test.team1_won, test.p_team1):.4f} "
          f"vs Elo {metrics.log_loss(test.team1_won, test.p_elo):.4f}")
    print("\nStandardised coefficients by test season:")
    print(coef.round(3).to_string())
    print("\nCalibration (favourite's predicted vs observed win rate):")
    print(calibration.round(3).to_string())


if __name__ == "__main__":
    main()
