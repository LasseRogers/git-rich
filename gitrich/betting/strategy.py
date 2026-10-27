from dataclasses import dataclass

from gitrich.betting import staking
from gitrich.odds.prices import fair_probability

SHARP = "pinnacle"
STAKE = 20.0
MIN_EDGE = 0.03
# Edges this large against the market are almost always model errors.
MAX_EDGE = 0.15


@dataclass(frozen=True)
class Bet:
    bookmaker: str
    selection: str
    price: float
    p_model: float
    p_market: float
    edge: float
    stake: float


def choose(p_team1: float, quotes: dict[tuple[str, str], float], cross_league: bool) -> Bet | None:
    """The best-paying bet on a match within the rules, if any. Quotes are keyed by (bookmaker, selection)."""
    # The model overrates weaker regions in international games.
    if cross_league:
        return None
    # Without the sharp line there's nothing to sanity-check the model against or to measure CLV with.
    if (SHARP, "team1") not in quotes or (SHARP, "team2") not in quotes:
        return None
    market_team1 = fair_probability(quotes[(SHARP, "team1")], quotes[(SHARP, "team2")])

    best = None
    for (bookmaker, selection), price in quotes.items():
        p = p_team1 if selection == "team1" else 1 - p_team1
        edge = staking.expected_value(p, price)
        if MIN_EDGE <= edge <= MAX_EDGE and (best is None or edge > best.edge):
            best = Bet(bookmaker, selection, price, p,
                       market_team1 if selection == "team1" else 1 - market_team1,
                       edge, STAKE)
    return best
