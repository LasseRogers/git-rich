import argparse
import logging
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd

from gitrich.db import connect
from gitrich.lol.data import load_games, load_matches
from gitrich.models import features, metrics, registry

log = logging.getLogger("train-lgbm")

EXPERIMENT = "lol-series"

PARAMS = {
    "objective": "binary",
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_child_samples": 200,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
}


def fit(train: pd.DataFrame, valid: pd.DataFrame, cols: list[str], seed: int) -> lgb.Booster:
    # Train on both orientations so the model can't learn anything from which team is listed first.
    X = pd.concat([train[cols], features.flip(train[cols])], ignore_index=True)
    y = np.concatenate([train.team1_won, ~train.team1_won.to_numpy(dtype=bool)]).astype(int)
    Xv = pd.concat([valid[cols], features.flip(valid[cols])], ignore_index=True)
    yv = np.concatenate([valid.team1_won, ~valid.team1_won.to_numpy(dtype=bool)]).astype(int)
    return lgb.train(
        {**PARAMS, "seed": seed},
        lgb.Dataset(X, y),
        num_boost_round=3000,
        valid_sets=[lgb.Dataset(Xv, yv)],
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )


def train_all(df: pd.DataFrame, cols: list[str], rounds: int) -> lgb.Booster:
    X = pd.concat([df[cols], features.flip(df[cols])], ignore_index=True)
    y = np.concatenate([df.team1_won, ~df.team1_won.to_numpy(dtype=bool)]).astype(int)
    return lgb.train({**PARAMS, "seed": 0}, lgb.Dataset(X, y), num_boost_round=rounds)


def predict(model: lgb.Booster, X: pd.DataFrame) -> np.ndarray:
    return (model.predict(X) + 1 - model.predict(features.flip(X))) / 2


def main() -> None:
    parser = argparse.ArgumentParser(prog="train-lgbm", description="Walk-forward LightGBM on pre-series features.")
    parser.add_argument("--groups", default=",".join(features.GROUPS),
                        help=f"feature groups, from: {', '.join(features.GROUPS)}")
    parser.add_argument("--train-from", type=int, default=2016)
    parser.add_argument("--test-from", type=int, default=2023)
    parser.add_argument("--k-league", type=float, default=16.0)
    parser.add_argument("--name", help="MLflow run name")
    parser.add_argument("--if-older-than", type=int, metavar="DAYS",
                        help="only train if the newest registered model is at least this many days old")
    parser.add_argument("--fail-unless-promoted", action="store_true",
                        help="exit with an error if the new model doesn't become the champion")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.if_older_than is not None:
        age = registry.latest_age()
        if age is not None and age < timedelta(days=args.if_older_than):
            log.info("newest model is %d days old, not retraining", age.days)
            return

    groups = args.groups.split(",")
    cols = features.columns(groups)

    with connect() as conn:
        games = load_games(conn)
        matches = load_matches(conn)
    df = features.build(games, matches, k_league=args.k_league)
    df = df[df.year >= args.train_from]
    log.info("%d series with features", len(df))

    # Each test season is predicted by a model trained on everything up to two seasons before it,
    # with the season in between used for early stopping.
    predictions, importance, rounds = [], [], []
    for year in sorted(y for y in df.year.unique() if y >= args.test_from):
        train, valid, test = df[df.year < year - 1], df[df.year == year - 1], df[df.year == year]
        if train.empty or valid.empty:
            continue
        model = fit(train, valid, cols, seed=year)
        out = test[["match_id", "league", "year", "start_time", "best_of", "team1_id", "team2_id", "team1_won"]].copy()
        out["p_team1"] = predict(model, test[cols])
        out["p_elo"] = 1 / (1 + np.exp(-test.elo_series_logit))
        predictions.append(out)
        importance.append(pd.Series(model.feature_importance("gain"), index=cols, name=year))
        rounds.append(model.best_iteration)
        log.info("%d: %d trees, log loss %.4f (elo %.4f)", year, model.best_iteration,
                 metrics.log_loss(out.team1_won, out.p_team1), metrics.log_loss(out.team1_won, out.p_elo))

    preds = pd.concat(predictions, ignore_index=True)
    by_year = pd.DataFrame({
        year: {"n": len(g), "log_loss": metrics.log_loss(g.team1_won, g.p_team1),
               "elo_log_loss": metrics.log_loss(g.team1_won, g.p_elo),
               "accuracy": metrics.accuracy(g.team1_won, g.p_team1)}
        for year, g in preds.groupby("year")
    }).T
    gain = pd.concat(importance, axis=1).mean(axis=1).sort_values(ascending=False)
    gain = (gain / gain.sum()).rename("share_of_gain")
    calibration = metrics.calibration(preds.team1_won, preds.p_team1)
    # Seasons with only a handful of series (e.g. preseason events filed under next year) are too noisy to score.
    test = preds[preds.groupby("year").year.transform("size") >= 200]

    # The production model sees every season; the tree count comes from the walk-forward early stopping.
    final = train_all(df, cols, int(np.mean(rounds)))

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=args.name or "+".join(groups)) as run:
        mlflow.set_tags({"predictions": "series", "model": "lgbm"})
        mlflow.log_params({"groups": args.groups, "train_from": args.train_from, "test_from": args.test_from,
                           "k_league": args.k_league, **{f"lgb_{k}": v for k, v in PARAMS.items()}})
        mlflow.log_metrics({f"test_{k}": v for k, v in metrics.summary(test.team1_won, test.p_team1).items()})
        mlflow.log_metric("final_trees", final.num_trees())
        mlflow.log_metric("test_elo_log_loss", metrics.log_loss(test.team1_won, test.p_elo))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            preds.drop(columns="p_elo").to_parquet(tmp / "series_predictions.parquet", index=False)
            by_year.to_csv(tmp / "by_year.csv", index_label="year")
            gain.to_csv(tmp / "feature_importance.csv", index_label="feature")
            calibration.to_csv(tmp / "calibration_test.csv", index_label="bucket")
            registry.save(final, cols, args.k_league, tmp / "model")
            mlflow.log_artifacts(str(tmp))
        version, promoted = registry.register(run.info.run_id, test)

    print(f"\nRun: {run.info.run_id}   groups: {args.groups}")
    print(f"Registered {registry.MODEL_NAME} v{version}" + (" as champion" if promoted else ", champion unchanged") + "\n")
    print(by_year.round(4).to_string())
    print(f"\nTest log loss {metrics.log_loss(test.team1_won, test.p_team1):.4f} "
          f"vs Elo {metrics.log_loss(test.team1_won, test.p_elo):.4f}")
    print("\nFeature importance (share of gain):")
    print(gain.round(3).to_string())
    print("\nCalibration (favourite's predicted vs observed win rate):")
    print(calibration.round(3).to_string())

    if args.fail_unless_promoted and not promoted:
        sys.exit(f"v{version} predicts the champion's test matches worse, so the champion was kept")


if __name__ == "__main__":
    main()
