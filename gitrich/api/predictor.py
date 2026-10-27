import logging
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from gitrich.db import connect
from gitrich.lol.data import load_games
from gitrich.models import features, registry
from gitrich.models.train_lgbm import predict

log = logging.getLogger(__name__)

MODEL_NAME = "lgbm"
BEST_OF = (1, 3, 5)


class Predictor:
    """Champion model plus the feature state after every game in the database."""

    def __init__(self):
        self._lock = threading.Lock()
        self.model: registry.LoadedModel | None = None
        self.state: features.FeatureState | None = None
        self.games = 0
        self.loaded_at: datetime | None = None

    def load(self) -> None:
        model = registry.load_champion()
        if model is None:
            log.warning("no champion model registered; run train-lgbm")
            return
        with connect() as conn:
            games = load_games(conn)
        _, state = features.replay(games, k_league=model.k_league)
        with self._lock:
            self.model, self.state, self.games = model, state, len(games)
            self.loaded_at = datetime.now(timezone.utc)
        log.info("model v%s, state after %d games", model.version, len(games))

    @property
    def ready(self) -> bool:
        return self.model is not None

    def predict(self, team1: int, team2: int, when: datetime) -> dict:
        """Series win probability for team1 under each format, plus the assumed lineups."""
        with self._lock:
            rows, lineups = [], None
            for best_of in BEST_OF:
                row, players1, players2 = self.state.upcoming(team1, team2, when, best_of)
                rows.append(row)
                lineups = (players1, players2)
            X = pd.DataFrame(rows)[self.model.columns]
            p = predict(self.model.booster, X)
        return {
            "p_team1": {bo: float(v) for bo, v in zip(BEST_OF, p)},
            "lineup_team1": lineups[0],
            "lineup_team2": lineups[1],
            "features": {k: _json(v) for k, v in rows[BEST_OF.index(3)].items()},
        }


def _json(value):
    return None if isinstance(value, float) and np.isnan(value) else value
