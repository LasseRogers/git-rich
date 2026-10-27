import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LN10_400 = math.log(10) / 400


@dataclass(frozen=True)
class EloParams:
    # "player": a team is the mean of its five players, so ratings survive roster moves and rebrands.
    mode: str = "player"
    k: float = 32.0
    k_provisional: float = 64.0
    provisional_games: int = 10
    # Share of the gap to the league mean closed per calendar year.
    season_regression: float = 0.25
    # Weight of each game in the running league mean that new entities start from.
    league_ema: float = 0.02
    initial: float = 1500.0


@dataclass
class EloState:
    params: EloParams
    rating: dict = field(default_factory=dict)
    games: dict = field(default_factory=dict)
    last_year: dict = field(default_factory=dict)
    last_league: dict = field(default_factory=dict)
    league_mean: dict = field(default_factory=dict)
    # Beta(50, 50) prior on blue winning, so the side term starts neutral and learns walk-forward.
    blue_wins: float = 50.0
    blue_games: float = 100.0

    def get(self, entity, league: str, year: int) -> float:
        p = self.params
        mean = self.league_mean.get(league, p.initial)
        if entity not in self.rating:
            self.rating[entity] = mean
            self.games[entity] = 0
        elif year > self.last_year[entity]:
            home = self.league_mean.get(self.last_league[entity], p.initial)
            shrink = 1 - (1 - p.season_regression) ** (year - self.last_year[entity])
            self.rating[entity] += shrink * (home - self.rating[entity])
        self.last_year[entity] = year
        self.last_league[entity] = league
        return self.rating[entity]

    def update(self, entity, delta: float) -> None:
        p = self.params
        k = p.k_provisional if self.games[entity] < p.provisional_games else p.k
        self.rating[entity] += k * delta
        self.games[entity] += 1


def run(games: pd.DataFrame, params: EloParams) -> tuple[pd.DataFrame, EloState]:
    """Walk-forward ratings: every probability uses only games before it."""
    state = EloState(params)
    out = np.full((len(games), 2), np.nan)

    player_mode = params.mode == "player"
    for i, g in enumerate(games.itertuples(index=False)):
        if player_mode:
            blue, red = list(g.blue_players), list(g.red_players)
            if not blue or not red:
                continue
        else:
            blue, red = [g.blue_team_id], [g.red_team_id]

        rb = sum(state.get(e, g.league, g.year) for e in blue) / len(blue)
        rr = sum(state.get(e, g.league, g.year) for e in red) / len(red)

        diff = (rb - rr) * LN10_400
        side = math.log(state.blue_wins / (state.blue_games - state.blue_wins))
        p_blue = 1 / (1 + math.exp(-(diff + side)))
        out[i] = (p_blue, 1 / (1 + math.exp(-diff)))

        mean = state.league_mean.get(g.league, params.initial)
        state.league_mean[g.league] = mean + params.league_ema * ((rb + rr) / 2 - mean)

        delta = float(g.blue_won) - p_blue
        for e in blue:
            state.update(e, delta)
        for e in red:
            state.update(e, -delta)
        state.blue_wins += float(g.blue_won)
        state.blue_games += 1

    result = games[["game_id", "match_id", "league", "year", "played_at", "blue_team_id", "red_team_id", "blue_won"]].copy()
    result["p_blue"] = out[:, 0]
    result["p_blue_neutral"] = out[:, 1]
    return result, state


def series_probability(p_game: np.ndarray, best_of: np.ndarray) -> np.ndarray:
    """Probability of winning a best-of-n series given a per-game win probability."""
    p = np.asarray(p_game, dtype=float)
    q = 1 - p
    out = np.empty_like(p)
    for n in np.unique(best_of):
        mask = best_of == n
        need = (int(n) + 1) // 2
        total = np.zeros(mask.sum())
        for losses in range(need):
            total += math.comb(need - 1 + losses, losses) * p[mask] ** need * q[mask] ** losses
        out[mask] = total
    return out


def series_predictions(game_preds: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Pre-series probability for team1, from ratings before the series' first game."""
    first = (
        game_preds.dropna(subset=["match_id", "p_blue_neutral"])
        .sort_values("played_at")
        .drop_duplicates("match_id")
        [["match_id", "year", "blue_team_id", "p_blue_neutral"]]
    )
    df = matches.merge(first, on="match_id")
    p_team1_game = np.where(df["blue_team_id"] == df["team1_id"], df["p_blue_neutral"], 1 - df["p_blue_neutral"])
    df["p_team1"] = series_probability(p_team1_game, df["best_of"].to_numpy())
    return df[["match_id", "league", "year", "start_time", "best_of", "team1_id", "team2_id", "team1_won", "p_team1"]]
