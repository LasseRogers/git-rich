from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def games() -> pd.DataFrame:
    """Two seasons of Bo1s between four teams of one league, with one roster change halfway."""
    rng = np.random.default_rng(7)
    rosters = {t: [10 * t + i for i in range(5)] for t in range(1, 5)}
    start = datetime(2025, 1, 6, 16, tzinfo=timezone.utc)
    rows = []
    for n in range(400):
        if n == 200:
            rosters[3] = rosters[3][:4] + [99]
        blue, red = (int(t) for t in rng.choice(list(rosters), 2, replace=False))
        played = start + timedelta(hours=40 * n)
        rows.append(dict(
            game_id=str(n), match_id=n, league="LEC", year=played.year, played_at=played, game_number=1,
            duration_s=1800, blue_team_id=blue, red_team_id=red, blue_won=bool(rng.random() < 0.5 + 0.1 * (blue - red)),
            blue_gold_diff_15=float(rng.normal(0, 1500)), blue_players=rosters[blue], red_players=rosters[red],
            blue_champions=[f"c{rng.integers(40)}" for _ in range(5)],
            red_champions=[f"c{rng.integers(40)}" for _ in range(5)],
        ))
    return pd.DataFrame(rows)
