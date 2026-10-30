import numpy as np
import pandas as pd

EPS = 1e-6
BOOTSTRAP_SAMPLES = 1000

# Each region's top flight and the international events, where nearly all bets are placed.
MAJOR_LEAGUES = frozenset({
    "LCK", "LPL", "LEC", "LCS", "LTA N", "LTA S", "CBLOL", "LCP", "PCS", "VCS", "LJL", "WLDs", "MSI", "FST",
})


def log_loss(y, p) -> float:
    return float(np.mean(_losses(y, p)))


def brier(y, p) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def accuracy(y, p) -> float:
    return float(np.mean((np.asarray(p) > 0.5) == np.asarray(y, dtype=bool)))


def summary(y, p) -> dict:
    return {"n": int(len(y)), "log_loss": log_loss(y, p), "brier": brier(y, p), "accuracy": accuracy(y, p),
            "ece": ece(y, p)}


def breakdown(df: pd.DataFrame) -> dict:
    """Log loss on the slices that matter for betting: major leagues, and single games vs longer series."""
    out = {}
    for name, mask in {"major": df.league.isin(MAJOR_LEAGUES), "bo1": df.best_of == 1, "bo3_bo5": df.best_of > 1}.items():
        part = df[mask]
        out[f"{name}_n"] = len(part)
        if len(part):
            out[f"{name}_log_loss"] = log_loss(part.team1_won, part.p_team1)
    return out


def gain(y, p_base, p_new, samples: int = BOOTSTRAP_SAMPLES, seed: int = 0) -> tuple[float, float, float]:
    """How much lower p_new's log loss is than p_base's, with a 95% bootstrap interval over matches.
    An interval that includes zero means the difference could be luck."""
    diff = _losses(y, p_base) - _losses(y, p_new)
    rng = np.random.default_rng(seed)
    means = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(samples)]
    low, high = np.percentile(means, [2.5, 97.5])
    return float(diff.mean()), float(low), float(high)


def ece(y, p, bins: int = 10) -> float:
    """Expected calibration error: the average gap between predicted and observed win rates, weighted by matches."""
    table = calibration(y, p, bins)
    return float((table.n * (table.predicted - table.observed).abs()).sum() / table.n.sum())


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


def _losses(y, p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))
