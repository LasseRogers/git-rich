import argparse
import logging
import tempfile
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd

from gitrich.db import connect
from gitrich.models import metrics
from gitrich.odds.prices import fair_probability, match_prices

log = logging.getLogger("backtest")

EXPERIMENT = "lol-backtest"
SHARP = "pinnacle"


def simulate(preds: pd.DataFrame, prices: pd.DataFrame, bookmaker: str, threshold: float, entry: str) -> pd.DataFrame:
    """Flat one-unit bets on the side with the larger edge, at most one bet per match."""
    book = prices[prices.bookmaker == bookmaker]
    sharp = prices[prices.bookmaker == SHARP][["match_id", "closing_team1", "closing_team2"]]
    sharp = sharp.assign(fair_close_team1=fair_probability(sharp.closing_team1, sharp.closing_team2))

    df = preds.merge(book, on="match_id").merge(sharp[["match_id", "fair_close_team1"]], on="match_id", how="left")
    if df.empty:
        return df

    price1, price2 = df[f"{entry}_team1"], df[f"{entry}_team2"]
    edge1 = df.p_team1 * price1 - 1
    edge2 = (1 - df.p_team1) * price2 - 1
    team1 = edge1 >= edge2

    df["side"] = np.where(team1, "team1", "team2")
    df["price"] = np.where(team1, price1, price2)
    df["p_model"] = np.where(team1, df.p_team1, 1 - df.p_team1)
    df["edge"] = np.where(team1, edge1, edge2)
    df["won"] = np.where(team1, df.team1_won, ~df.team1_won.astype(bool))
    fair_close = np.where(team1, df.fair_close_team1, 1 - df.fair_close_team1)
    # Closing line value: how much better our price was than the sharp, margin-free closing price.
    df["clv"] = df.price * fair_close - 1

    bets = df[df.edge > threshold].copy()
    bets["profit"] = np.where(bets.won, bets.price - 1, -1.0)
    return bets


def market_comparison(preds: pd.DataFrame, prices: pd.DataFrame) -> dict:
    sharp = prices[prices.bookmaker == SHARP]
    df = preds.merge(sharp, on="match_id")
    if df.empty:
        return {"matches": 0}
    fair = fair_probability(df.closing_team1, df.closing_team2)
    return {
        "matches": len(df),
        "model_log_loss": metrics.log_loss(df.team1_won, df.p_team1),
        "market_log_loss": metrics.log_loss(df.team1_won, fair),
    }


def summarize(bets: pd.DataFrame) -> dict:
    if bets.empty:
        return {"bets": 0}
    return {
        "bets": len(bets),
        "profit": float(bets.profit.sum()),
        "roi": float(bets.profit.mean()),
        "hit_rate": float(bets.won.mean()),
        "avg_price": float(bets.price.mean()),
        "avg_edge": float(bets.edge.mean()),
        "avg_clv": float(bets.clv.mean()),
        "beat_close_rate": float((bets.clv.dropna() > 0).mean()) if bets.clv.notna().any() else float("nan"),
    }


def load_predictions(experiment: str, run_id: str | None) -> tuple[str, pd.DataFrame]:
    if run_id is None:
        runs = mlflow.search_runs(
            experiment_names=[experiment],
            filter_string="tags.predictions = 'series' AND attributes.status = 'FINISHED'",
            order_by=["attributes.start_time DESC"],
            max_results=1,
        )
        if runs.empty:
            raise SystemExit(f"no finished run in {experiment}; train a model first")
        run_id = runs.run_id.iloc[0]
    path = mlflow.artifacts.download_artifacts(run_id=run_id, artifact_path="series_predictions.parquet")
    return run_id, pd.read_parquet(path)


def main() -> None:
    parser = argparse.ArgumentParser(prog="backtest", description="Bet model predictions against collected odds.")
    parser.add_argument("--experiment", default="lol-series-elo")
    parser.add_argument("--run", help="MLflow run with series_predictions.parquet; defaults to the latest")
    parser.add_argument("--bookmaker", default=SHARP)
    parser.add_argument("--threshold", type=float, default=0.03, help="minimum expected value per unit staked")
    parser.add_argument("--entry", choices=["opening", "closing"], default="opening",
                        help="bet at the first or the last pre-match price we captured")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    run_id, preds = load_predictions(args.experiment, args.run)
    with connect() as conn:
        prices = match_prices(conn)
    log.info("%d predictions from run %s, %d matches with odds", len(preds), run_id, prices.match_id.nunique())

    bets = simulate(preds, prices, args.bookmaker, args.threshold, args.entry)
    result = summarize(bets)
    market = market_comparison(preds, prices)

    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f"{args.experiment} {args.bookmaker} {args.entry}"):
        mlflow.log_params({"source_experiment": args.experiment, "source_run": run_id, "bookmaker": args.bookmaker,
                           "threshold": args.threshold, "entry": args.entry})
        mlflow.log_metrics({k: v for k, v in {**result, **{f"market_{k}": v for k, v in market.items()}}.items()
                            if v == v})
        if not bets.empty:
            with tempfile.TemporaryDirectory() as tmp:
                bets.to_parquet(Path(tmp) / "bets.parquet", index=False)
                mlflow.log_artifact(str(Path(tmp) / "bets.parquet"))

    print()
    print(pd.Series({**result, **{f"market_{k}": v for k, v in market.items()}}).to_string())
    if result["bets"] and result["bets"] < 300:
        print(f"\nOnly {result['bets']} bets: ROI is mostly noise at this sample size. CLV converges much faster.")


if __name__ == "__main__":
    main()
