import pandas as pd
import psycopg


def match_prices(conn: psycopg.Connection, market: str = "winner") -> pd.DataFrame:
    """Opening and closing pre-match prices per linked match and bookmaker, oriented to core.matches.team1."""
    rows = conn.execute(
        """
        WITH p AS (
            SELECT e.match_id, s.bookmaker, s.price, s.captured_at,
                   -- OddsPapi's participant order is arbitrary; flip selections to our team1/team2.
                   CASE WHEN e.home_team_id = m.team1_id THEN s.selection
                        WHEN s.selection = 'team1' THEN 'team2' ELSE 'team1' END AS side
            FROM core.odds_snapshots s
            JOIN core.odds_events e ON e.id = s.odds_event_id
            JOIN core.matches m ON m.id = e.match_id
            WHERE s.market = %s AND s.active AND s.captured_at < e.start_time
        )
        SELECT match_id, bookmaker, side,
               (array_agg(price ORDER BY captured_at))[1] AS opening,
               (array_agg(price ORDER BY captured_at DESC))[1] AS closing,
               count(*) AS snapshots
        FROM p
        GROUP BY match_id, bookmaker, side
        """,
        (market,),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["match_id", "bookmaker", "side", "opening", "closing", "snapshots"])
    if df.empty:
        return pd.DataFrame(columns=["match_id", "bookmaker", "opening_team1", "opening_team2",
                                     "closing_team1", "closing_team2"])

    df[["opening", "closing"]] = df[["opening", "closing"]].astype(float)
    wide = df.pivot_table(index=["match_id", "bookmaker"], columns="side", values=["opening", "closing"])
    wide.columns = [f"{value}_{side}" for value, side in wide.columns]
    # A two-way market needs both sides; one-sided rows can't be de-vigged or compared.
    return wide.dropna().reset_index()


def fair_probability(price_team1, price_team2):
    """Bookmaker margin removed proportionally."""
    inv1, inv2 = 1 / price_team1, 1 / price_team2
    return inv1 / (inv1 + inv2)
