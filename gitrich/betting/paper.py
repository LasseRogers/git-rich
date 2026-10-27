from datetime import timedelta

import psycopg

from gitrich.betting.strategy import choose

# Every match is bet as if decided this long before the start, whenever the decision actually runs.
LEAD = timedelta(hours=12)
# Prices older than this at decision time are too stale to have been bettable.
MAX_PRICE_AGE = timedelta(hours=12)


def quotes_at(conn: psycopg.Connection, event_id: int, at) -> dict[tuple[str, str], float]:
    rows = conn.execute(
        """
        SELECT DISTINCT ON (bookmaker, selection) bookmaker, selection, price
        FROM core.odds_snapshots
        WHERE odds_event_id = %s AND market = 'winner' AND active AND captured_at BETWEEN %s AND %s
        ORDER BY bookmaker, selection, captured_at DESC
        """,
        (event_id, at - MAX_PRICE_AGE, at),
    ).fetchall()
    return {(bookmaker, selection): float(price) for bookmaker, selection, price in rows}


def played_since(conn: psycopg.Connection, team_ids: list[int], at) -> bool:
    """A result after decision time would leak into the prediction."""
    return conn.execute(
        """
        SELECT EXISTS (SELECT 1 FROM core.matches
                       WHERE start_time > %s AND (team1_id = ANY(%s) OR team2_id = ANY(%s)))
        """,
        (at, team_ids, team_ids),
    ).fetchone()[0]


def place(conn: psycopg.Connection, matches: list[dict]) -> int:
    """Logs a paper bet on every match the strategy picks, priced as at decision time, at most one per match."""
    placed = 0
    for m in matches:
        at = m["start_time"] - LEAD
        teams = [m["team1"]["id"], m["team2"]["id"]]
        if played_since(conn, teams, at):
            continue
        bet = choose(m["p_team1"], quotes_at(conn, m["odds_event_id"], at), m["cross_league"])
        if bet is None:
            continue
        cur = conn.execute(
            """
            INSERT INTO core.bets (odds_event_id, prediction_id, team_id, selection, bookmaker,
                                   price, stake, p_model, p_market, mode, placed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'paper', %s)
            ON CONFLICT (odds_event_id) WHERE mode = 'paper' DO NOTHING
            """,
            (m["odds_event_id"], m["prediction_id"], teams[0 if bet.selection == "team1" else 1], bet.selection,
             bet.bookmaker, bet.price, bet.stake, bet.p_model, bet.p_market, at),
        )
        placed += cur.rowcount
    return placed
