import pandas as pd
import psycopg


def load_games(conn: psycopg.Connection) -> pd.DataFrame:
    rows = conn.execute("""
        SELECT g.game_id, g.match_id, g.league, g.year, g.played_at, g.game_number,
               g.blue_team_id, g.red_team_id, g.winner_side = 'blue' AS blue_won,
               coalesce(array_agg(p.player_id ORDER BY p.position) FILTER (WHERE p.side = 'blue'), '{}') AS blue_players,
               coalesce(array_agg(p.player_id ORDER BY p.position) FILTER (WHERE p.side = 'red'), '{}') AS red_players
        FROM lol.games g
        LEFT JOIN lol.player_stats p ON p.game_id = g.game_id
        GROUP BY g.game_id
        ORDER BY g.played_at, g.game_number NULLS FIRST, g.game_id
    """).fetchall()
    columns = ["game_id", "match_id", "league", "year", "played_at", "game_number",
               "blue_team_id", "red_team_id", "blue_won", "blue_players", "red_players"]
    return pd.DataFrame(rows, columns=columns)


def load_matches(conn: psycopg.Connection) -> pd.DataFrame:
    rows = conn.execute("""
        SELECT id AS match_id, league, start_time, best_of, team1_id, team2_id,
               winner_id = team1_id AS team1_won
        FROM core.matches
        WHERE title = 'lol' AND status = 'finished' AND winner_id IS NOT NULL
        ORDER BY start_time
    """).fetchall()
    return pd.DataFrame(rows, columns=["match_id", "league", "start_time", "best_of",
                                       "team1_id", "team2_id", "team1_won"])
