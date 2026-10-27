import argparse
import itertools
import logging
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

import mlflow
import pandas as pd

from gitrich.db import connect
from gitrich.lol.data import load_games, load_matches
from gitrich.models import elo, metrics

log = logging.getLogger("train-elo")

EXPERIMENT = "lol-series-elo"

GRID = {
    "mode": ["team", "player"],
    "k": [16.0, 24.0, 32.0, 48.0, 64.0],
    "season_regression": [0.25, 0.5, 0.75],
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="train-elo", description="Tune and evaluate the Elo baseline.")
    parser.add_argument("--valid-from", type=int, default=2019, help="first season used for tuning")
    parser.add_argument("--test-from", type=int, default=2023, help="first held-out season, never used for tuning")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with connect() as conn:
        games = load_games(conn)
        matches = load_matches(conn)
    log.info("%d games, %d series", len(games), len(matches))

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name="grid") as parent:
        mlflow.set_tag("predictions", "series")
        mlflow.log_params({"valid_from": args.valid_from, "test_from": args.test_from, "games": len(games)})

        results = []
        for values in itertools.product(*GRID.values()):
            params = replace(elo.EloParams(), **dict(zip(GRID, values)))
            game_preds, _ = elo.run(games, params)
            series = elo.series_predictions(game_preds, matches)
            valid = series[(series.year >= args.valid_from) & (series.year < args.test_from)]
            score = metrics.summary(valid.team1_won, valid.p_team1)

            with mlflow.start_run(run_name=_name(params), nested=True):
                mlflow.log_params(asdict(params))
                mlflow.log_metrics({f"valid_{k}": v for k, v in score.items()})
            log.info("%s valid log loss %.4f", _name(params), score["log_loss"])
            results.append((score["log_loss"], params))

        best_loss, best = min(results, key=lambda r: r[0])
        log.info("best %s (valid log loss %.4f)", _name(best), best_loss)

        game_preds, state = elo.run(games, best)
        series = elo.series_predictions(game_preds, matches)
        test = series[series.year >= args.test_from]

        mlflow.log_params({f"best_{k}": v for k, v in asdict(best).items()})
        mlflow.log_metrics({f"test_{k}": v for k, v in metrics.summary(test.team1_won, test.p_team1).items()})
        mlflow.log_metrics({"test_coinflip_log_loss": metrics.log_loss(test.team1_won, [0.5] * len(test))})

        by_year = pd.DataFrame(
            {year: metrics.summary(g.team1_won, g.p_team1) for year, g in series.groupby("year")}
        ).T
        calibration = metrics.calibration(test.team1_won, test.p_team1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            by_year.to_csv(tmp / "by_year.csv", index_label="year")
            calibration.to_csv(tmp / "calibration_test.csv", index_label="bucket")
            series.to_parquet(tmp / "series_predictions.parquet", index=False)
            pd.DataFrame(
                {"entity": list(state.rating), "rating": list(state.rating.values()),
                 "games": [state.games[e] for e in state.rating],
                 "last_league": [state.last_league[e] for e in state.rating]}
            ).to_parquet(tmp / "ratings.parquet", index=False)
            mlflow.log_artifacts(str(tmp))

        print(f"\nBest: {_name(best)}   run: {parent.info.run_id}\n")
        print(by_year.round(4).to_string())
        print("\nCalibration on test seasons (favourite's predicted vs observed win rate):")
        print(calibration.round(3).to_string())


def _name(p: elo.EloParams) -> str:
    return f"{p.mode} k={p.k:g} reg={p.season_regression:g}"


if __name__ == "__main__":
    main()
