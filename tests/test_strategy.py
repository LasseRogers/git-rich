import pytest

from gitrich.betting.strategy import MAX_EDGE, MIN_EDGE, SHARP, choose, choose_sharp

# Pinnacle at 2.00 / 2.00 makes the fair probability exactly 0.5 for each side.
EVEN = {(SHARP, "team1"): 2.0, (SHARP, "team2"): 2.0}


def test_choose_needs_both_pinnacle_sides():
    assert choose(0.6, {(SHARP, "team1"): 2.0, ("bet365", "team1"): 2.0}, cross_league=False) is None


def test_choose_skips_cross_league_matches():
    assert choose(0.6, {**EVEN, ("bet365", "team1"): 2.0}, cross_league=True) is None


def test_choose_takes_the_best_edge_within_the_limits():
    # p=0.53 at 2.00 is a 6% edge; at 2.05 it is 8.65%; at 2.30 it is 21.9%, beyond MAX_EDGE.
    quotes = {**EVEN, ("bet365", "team1"): 2.05, ("unibet", "team1"): 2.30, ("bwin", "team2"): 2.0}
    bet = choose(0.53, quotes, cross_league=False)
    assert (bet.bookmaker, bet.selection, bet.price) == ("bet365", "team1", 2.05)
    assert bet.edge == pytest.approx(0.53 * 2.05 - 1)
    assert bet.p_model == 0.53 and bet.p_market == pytest.approx(0.5)


def test_choose_rejects_edges_outside_the_limits():
    small = 1 + MIN_EDGE / 2
    large = (1 + MAX_EDGE) * 1.1
    for price in (small / 0.5, large / 0.5):
        assert choose(0.5, {**EVEN, ("bet365", "team1"): price}, cross_league=False) is None


def test_choose_sharp_ignores_the_model_and_pinnacle_itself():
    quotes = {(SHARP, "team1"): 1.8, (SHARP, "team2"): 2.2, ("bet365", "team2"): 2.4, ("bwin", "team2"): 2.3}
    bet = choose_sharp(quotes)
    fair_team2 = (1 / 2.2) / (1 / 1.8 + 1 / 2.2)
    assert (bet.bookmaker, bet.selection) == ("bet365", "team2")
    assert bet.p_model is None
    assert bet.edge == pytest.approx(fair_team2 * 2.4 - 1)


def test_choose_sharp_finds_nothing_at_fair_prices():
    assert choose_sharp({**EVEN, ("bet365", "team1"): 2.0, ("bet365", "team2"): 2.0}) is None
