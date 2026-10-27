def expected_value(p: float, price: float) -> float:
    return p * price - 1


def kelly_fraction(p: float, price: float) -> float:
    """Share of bankroll that maximises long-run growth; zero when there's no edge."""
    if price <= 1:
        return 0.0
    return max(0.0, (p * price - 1) / (price - 1))


def stake(p: float, price: float, bankroll: float, fraction: float, cap: float) -> float:
    # Full Kelly assumes p is exact. Model error makes it ruinous, so it's scaled down and capped.
    return round(min(kelly_fraction(p, price) * fraction, cap) * bankroll, 2)
