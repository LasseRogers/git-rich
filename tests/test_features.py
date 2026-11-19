from datetime import timedelta

import numpy as np
import pandas as pd

from gitrich.models import features

UNSIGNED = {"cross_league", "best_of"}


def test_every_difference_feature_is_flipped():
    """A new *_diff feature that isn't in DIFF would keep its sign when the teams swap."""
    flipped = set(features.DIFF) | {"elo_series_logit"}
    for column in features.columns(list(features.GROUPS)):
        assert column in flipped or column in UNSIGNED, f"{column} is neither flipped nor known to be unsigned"


def test_flip_negates_differences_and_keeps_the_rest():
    cols = features.columns(list(features.GROUPS))
    X = pd.DataFrame([np.arange(1.0, len(cols) + 1)], columns=cols)
    out = features.flip(X)
    for c in cols:
        assert out[c].iloc[0] == (X[c].iloc[0] if c in UNSIGNED else -X[c].iloc[0])
    pd.testing.assert_frame_equal(features.flip(out), X)


def test_swapping_the_teams_mirrors_the_features(games):
    """What the API sees for team1 vs team2 must be the mirror image of team2 vs team1."""
    _, state = features.replay(games)
    when = games.played_at.max() + timedelta(days=1)
    for a, b in ((1, 2), (3, 4), (2, 3)):
        ab, _, _ = state.upcoming(a, b, when, best_of=3)
        ba, _, _ = state.upcoming(b, a, when, best_of=3)
        for c in ab:
            expected = ba[c] if c in UNSIGNED else -ba[c]
            assert np.isclose(ab[c], expected, equal_nan=True), c


def test_upcoming_assumes_the_latest_lineup(games):
    _, state = features.replay(games)
    _, players, _ = state.upcoming(3, 1, games.played_at.max(), best_of=1)
    assert 99 in players and 34 not in players
