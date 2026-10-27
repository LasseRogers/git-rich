import psycopg

from gitrich.betting.strategy import SHARP


def settle(conn: psycopg.Connection) -> int:
    """Settles pending bets whose odds event is now linked to a finished match."""
    cur = conn.execute(
        """
        WITH closing AS (
            -- Last pre-match price per event, bookmaker and selection.
            SELECT DISTINCT ON (s.odds_event_id, s.bookmaker, s.market, s.selection)
                   s.odds_event_id, s.bookmaker, s.market, s.selection, s.price
            FROM core.odds_snapshots s
            JOIN core.odds_events e ON e.id = s.odds_event_id
            WHERE s.active AND s.captured_at < e.start_time
            ORDER BY s.odds_event_id, s.bookmaker, s.market, s.selection, s.captured_at DESC
        ),
        sharp AS (
            SELECT odds_event_id, market,
                   (1 / max(price) FILTER (WHERE selection = 'team1'))
                   / (1 / max(price) FILTER (WHERE selection = 'team1')
                      + 1 / max(price) FILTER (WHERE selection = 'team2')) AS fair_team1
            FROM closing
            WHERE bookmaker = %(sharp)s
            GROUP BY odds_event_id, market
        )
        UPDATE core.bets b SET
            match_id = e.match_id,
            result = CASE WHEN m.winner_id = b.team_id THEN 'won' ELSE 'lost' END,
            pnl = CASE WHEN m.winner_id = b.team_id THEN b.stake * (b.price - 1) ELSE -b.stake END,
            closing_price = (
                SELECT c.price FROM closing c
                WHERE c.odds_event_id = b.odds_event_id AND c.bookmaker = b.bookmaker
                  AND c.market = b.market AND c.selection = b.selection
            ),
            -- Against the sharp, margin-free closing price, whichever bookmaker the bet was placed with.
            clv = b.price * (
                SELECT CASE WHEN b.selection = 'team1' THEN sh.fair_team1 ELSE 1 - sh.fair_team1 END
                FROM sharp sh WHERE sh.odds_event_id = b.odds_event_id AND sh.market = b.market
            ) - 1,
            settled_at = now()
        FROM core.odds_events e
        JOIN core.matches m ON m.id = e.match_id
        WHERE b.odds_event_id = e.id
          AND b.result = 'pending'
          AND m.status = 'finished' AND m.winner_id IS NOT NULL
        """,
        {"sharp": SHARP},
    )
    return cur.rowcount
