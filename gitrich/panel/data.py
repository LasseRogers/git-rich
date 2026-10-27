import json
import os
import urllib.error
import urllib.request

import pandas as pd

from gitrich.db import connect

API_URL = os.environ.get("API_URL", "http://api:8000")

BETS = """
    SELECT b.id, e.start_time, e.tournament, t.name AS pick, o.name AS opponent,
           b.bookmaker, b.price::float AS price, b.stake::float AS stake, b.p_model, b.p_market, b.result
    FROM core.bets b
    JOIN core.teams t ON t.id = b.team_id
    JOIN core.odds_events e ON e.id = b.odds_event_id
    JOIN core.teams o ON o.id = CASE WHEN b.team_id = e.home_team_id THEN e.away_team_id ELSE e.home_team_id END
    WHERE b.mode = 'paper'
"""


def health() -> dict | None:
    try:
        with urllib.request.urlopen(f"{API_URL}/health", timeout=5) as resp:
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError):
        return None


def query(sql: str, params=None) -> pd.DataFrame:
    with connect() as conn:
        cur = conn.execute(sql, params)
        return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def upcoming_bets() -> pd.DataFrame:
    return query(BETS + " AND b.result = 'pending' AND e.start_time > now() ORDER BY e.start_time")


def settled_bets() -> pd.DataFrame:
    return query(BETS + " AND b.result IN ('won', 'lost') ORDER BY e.start_time")


def odds_updated():
    return query("SELECT max(captured_at) AS at FROM core.odds_snapshots").at[0, "at"]
