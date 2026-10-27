import numpy as np
import pandas as pd

EPS = 1e-6


def log_loss(y, p) -> float:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(y, p) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def accuracy(y, p) -> float:
    return float(np.mean((np.asarray(p) > 0.5) == np.asarray(y, dtype=bool)))


def summary(y, p) -> dict:
    return {"n": int(len(y)), "log_loss": log_loss(y, p), "brier": brier(y, p), "accuracy": accuracy(y, p)}


def calibration(y, p, bins: int = 10) -> pd.DataFrame:
    # Folded onto the favourite, since team1 vs team2 is an arbitrary order.
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    fav_p = np.where(p >= 0.5, p, 1 - p)
    fav_won = np.where(p >= 0.5, y, 1 - y)
    edges = np.linspace(0.5, 1.0, bins + 1)
    bucket = np.clip(np.digitize(fav_p, edges) - 1, 0, bins - 1)
    df = pd.DataFrame({"bucket": bucket, "predicted": fav_p, "observed": fav_won})
    out = df.groupby("bucket").agg(n=("observed", "size"), predicted=("predicted", "mean"), observed=("observed", "mean"))
    out.index = [f"{edges[i]:.2f}-{edges[i + 1]:.2f}" for i in out.index]
    return out
