"""Walk-forward pre-series features. Each row only sees games played before the series started."""
import math
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from gitrich.models import elo

WINDOW = 10
HOME_WINDOW = 20

# Difference features flip sign when the teams are swapped.
DIFF = [
    "elo_player_diff", "elo_team_diff", "league_offset_diff", "experience_diff",
    "form_diff", "momentum_diff", "gold_diff_15_diff", "rest_days_diff", "games_7d_diff",
]

GROUPS = {
    "elo": ["elo_player_diff", "elo_team_diff", "elo_series_logit"],
    "league": ["league_offset_diff", "cross_league"],
    "roster": ["experience_diff"],
    "form": ["form_diff", "momentum_diff", "gold_diff_15_diff"],
    "schedule": ["rest_days_diff", "games_7d_diff"],
    "format": ["best_of"],
}


@dataclass
class TeamHistory:
    results: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    ratings: deque = field(default_factory=lambda: deque(maxlen=WINDOW + 1))
    gold_diff_15: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    played_at: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    leagues: deque = field(default_factory=lambda: deque(maxlen=HOME_WINDOW))
    lineup: frozenset = frozenset()


class FeatureState:
    def __init__(self, k_league: float = 16.0):
        self.players = elo.EloState(elo.EloParams(mode="player", k=32, season_regression=0.5))
        self.teams = elo.EloState(elo.EloParams(mode="team", k=32, season_regression=0.5))
        self.history: dict[int, TeamHistory] = defaultdict(TeamHistory)
        # Region strength, learned only from games between teams with different home leagues.
        self.league_offset: dict[str, float] = defaultdict(float)
        self.k_league = k_league

    def home(self, team: int, fallback: str) -> str:
        leagues = self.history[team].leagues
        return Counter(leagues).most_common(1)[0][0] if leagues else fallback

    def snapshot(self, team1: int, team2: int, players1: list, players2: list,
                 league: str, year: int, when: datetime, best_of: int) -> dict:
        h1, h2 = self.history[team1], self.history[team2]
        home1, home2 = self.home(team1, league), self.home(team2, league)

        rp1 = self.players.strength(players1, league, year) if players1 else np.nan
        rp2 = self.players.strength(players2, league, year) if players2 else np.nan
        rt1, rt2 = self.teams.get(team1, league, year), self.teams.get(team2, league, year)
        offset = self.league_offset[home1] - self.league_offset[home2]

        p_game = elo.sigmoid((rp1 - rp2) * elo.LN10_400) if players1 and players2 else 0.5
        p_series = float(elo.series_probability(p_game, best_of)[0])

        return {
            "elo_player_diff": rp1 - rp2,
            "elo_team_diff": rt1 - rt2,
            "elo_series_logit": math.log(p_series / (1 - p_series)),
            "league_offset_diff": offset,
            "cross_league": float(home1 != home2),
            "experience_diff": _experience(self.players, players1) - _experience(self.players, players2),
            "form_diff": _mean(h1.results, 0.5) - _mean(h2.results, 0.5),
            "momentum_diff": _momentum(h1) - _momentum(h2),
            "gold_diff_15_diff": _mean(h1.gold_diff_15, np.nan) - _mean(h2.gold_diff_15, np.nan),
            "rest_days_diff": _rest_days(h1, when) - _rest_days(h2, when),
            "games_7d_diff": _games_since(h1, when, 7) - _games_since(h2, when, 7),
            "best_of": float(best_of),
        }

    def upcoming(self, team1: int, team2: int, when: datetime, best_of: int,
                 league: str = "") -> tuple[dict, list, list]:
        """Features for a match not yet played. Lineups are unknown, so each team's latest one is assumed.
        `league` only matters for teams without history."""
        players1 = sorted(self.history[team1].lineup)
        players2 = sorted(self.history[team2].lineup)
        league = self.home(team1, self.home(team2, league))
        row = self.snapshot(team1, team2, players1, players2, league, when.year, when, best_of)
        return row, players1, players2

    def update(self, game) -> None:
        blue_players, red_players = list(game.blue_players), list(game.red_players)
        home_blue = self.home(game.blue_team_id, game.league)
        home_red = self.home(game.red_team_id, game.league)

        if home_blue != home_red and blue_players and red_players:
            rb = self.players.strength(blue_players, game.league, game.year)
            rr = self.players.strength(red_players, game.league, game.year)
            gap = self.league_offset[home_blue] - self.league_offset[home_red]
            p = elo.sigmoid((rb - rr + gap) * elo.LN10_400 + self.players.side_logit)
            delta = self.k_league * (float(game.blue_won) - p)
            self.league_offset[home_blue] += delta
            self.league_offset[home_red] -= delta

        if blue_players and red_players:
            self.players.play(blue_players, red_players, game.league, game.year, game.blue_won)
        self.teams.play([game.blue_team_id], [game.red_team_id], game.league, game.year, game.blue_won)

        gd = game.blue_gold_diff_15
        for team, players, won, sign in ((game.blue_team_id, blue_players, game.blue_won, 1),
                                         (game.red_team_id, red_players, not game.blue_won, -1)):
            h = self.history[team]
            h.results.append(float(won))
            h.ratings.append(self.teams.rating[team])
            if gd is not None and not pd.isna(gd):
                h.gold_diff_15.append(sign * float(gd))
            h.played_at.append(game.played_at)
            h.leagues.append(game.league)
            if players:
                h.lineup = frozenset(players)


def build(games: pd.DataFrame, matches: pd.DataFrame, k_league: float = 16.0) -> pd.DataFrame:
    return replay(games, matches, k_league)[0]


def replay(games: pd.DataFrame, matches: pd.DataFrame | None = None,
           k_league: float = 16.0) -> tuple[pd.DataFrame, "FeatureState"]:
    """Walks all games in order. Returns per-series features and the state after the last game."""
    state = FeatureState(k_league)
    if matches is None:
        matches = pd.DataFrame(columns=["match_id", "league", "start_time", "best_of",
                                        "team1_id", "team2_id", "team1_won"])
    series = matches.set_index("match_id")
    rows = []
    seen = set()

    for g in games.itertuples(index=False):
        if g.match_id in series.index and g.match_id not in seen:
            seen.add(g.match_id)
            m = series.loc[g.match_id]
            # Built exactly as the API builds them before a match, when the lineups aren't known yet.
            row, _, _ = state.upcoming(int(m.team1_id), int(m.team2_id), g.played_at, int(m.best_of), g.league)
            row.update(match_id=g.match_id, year=g.year, league=m.league, start_time=m.start_time,
                       team1_id=m.team1_id, team2_id=m.team2_id, team1_won=bool(m.team1_won))
            rows.append(row)
        state.update(g)

    return pd.DataFrame(rows), state


def flip(X: pd.DataFrame) -> pd.DataFrame:
    """The same matches seen from the other team's side."""
    out = X.copy()
    for c in DIFF + ["elo_series_logit"]:
        if c in out:
            out[c] = -out[c]
    return out


def columns(groups: list[str]) -> list[str]:
    return [c for g in groups for c in GROUPS[g]]


def _experience(state: elo.EloState, players: list) -> float:
    if not players:
        return np.nan
    return float(np.mean([min(state.games.get(p, 0), 300) for p in players]))


def _mean(values, default: float) -> float:
    return float(np.mean(values)) if values else default


def _momentum(h: TeamHistory) -> float:
    return float(h.ratings[-1] - h.ratings[0]) if len(h.ratings) > 1 else 0.0


def _rest_days(h: TeamHistory, when: datetime) -> float:
    if not h.played_at:
        return 30.0
    return min((when - h.played_at[-1]).total_seconds() / 86400, 30.0)


def _games_since(h: TeamHistory, when: datetime, days: int) -> float:
    return float(sum((when - t).total_seconds() < days * 86400 for t in h.played_at))
