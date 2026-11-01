from dataclasses import dataclass

from gitrich.odds.prices import fair_probability

SHARP = "pinnacle"
STAKE = 20.0
MIN_EDGE = 0.03
# Edges this large against the market are almost always model errors, or stale prices a bookmaker would void.
MAX_EDGE = 0.15
# "model" bets where the model disagrees with the bookmakers; "sharp" bets wherever another bookmaker
# pays more than Pinnacle's margin-free price, with no model involved.
STRATEGIES = ("model", "sharp")
LABELS = {"model": "Model", "sharp": "Pinnacle line"}


@dataclass(frozen=True)
class Bet:
    bookmaker: str
    selection: str
    price: float
    p_model: float | None
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
        edge = p * price - 1
        if MIN_EDGE <= edge <= MAX_EDGE and (best is None or edge > best.edge):
            best = Bet(bookmaker, selection, price, p,
                       market_team1 if selection == "team1" else 1 - market_team1,
                       edge, STAKE)
    return best


def choose_sharp(quotes: dict[tuple[str, str], float]) -> Bet | None:
    """The best price another bookmaker offers above Pinnacle's margin-free one, within the same edge limits."""
    if (SHARP, "team1") not in quotes or (SHARP, "team2") not in quotes:
        return None
    fair_team1 = fair_probability(quotes[(SHARP, "team1")], quotes[(SHARP, "team2")])

    best = None
    for (bookmaker, selection), price in quotes.items():
        if bookmaker == SHARP:
            continue
        p = fair_team1 if selection == "team1" else 1 - fair_team1
        edge = p * price - 1
        if MIN_EDGE <= edge <= MAX_EDGE and (best is None or edge > best.edge):
            best = Bet(bookmaker, selection, price, None, p, edge, STAKE)
    return best
