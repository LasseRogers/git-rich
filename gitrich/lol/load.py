import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

SOURCE = "oracles_elixir"
TITLE = "lol"
POSITIONS = ("top", "jng", "mid", "bot", "sup")

# Games further apart than this between the same two teams belong to different series.
SERIES_GAP = pd.Timedelta(hours=8)

TEAM_STAT_COLUMNS = {
    "kills": "kills",
    "deaths": "deaths",
    "assists": "assists",
    "towers": "towers",
    "inhibitors": "inhibitors",
    "dragons": "dragons",
    "barons": "barons",
    "heralds": "heralds",
    "firstblood": "first_blood",
    "firstdragon": "first_dragon",
    "firstherald": "first_herald",
    "firstbaron": "first_baron",
    "firsttower": "first_tower",
    "golddiffat10": "gold_diff_10",
    "golddiffat15": "gold_diff_15",
    "xpdiffat10": "xp_diff_10",
    "xpdiffat15": "xp_diff_15",
    "csdiffat10": "cs_diff_10",
    "csdiffat15": "cs_diff_15",
}

PLAYER_STAT_COLUMNS = {
    "kills": "kills",
    "deaths": "deaths",
    "assists": "assists",
    "dpm": "damage_per_min",
    "damageshare": "damage_share",
    "vspm": "vision_per_min",
    "earned gpm": "earned_gpm",
    "cspm": "cs_per_min",
    "golddiffat10": "gold_diff_10",
    "golddiffat15": "gold_diff_15",
    "xpdiffat10": "xp_diff_10",
    "xpdiffat15": "xp_diff_15",
    "csdiffat10": "cs_diff_10",
    "csdiffat15": "cs_diff_15",
}

SOURCE_COLUMNS = [
    "gameid", "participantid", "datacompleteness", "league", "year", "split", "playoffs", "date",
    "game", "patch", "side", "position", "playername", "playerid", "teamname", "teamid", "champion",
    "ban1", "ban2", "ban3", "ban4", "ban5", "gamelength", "result",
    *dict.fromkeys([*TEAM_STAT_COLUMNS, *PLAYER_STAT_COLUMNS]),
]

FLAG_COLUMNS = {"first_blood", "first_dragon", "first_herald", "first_baron", "first_tower"}
FLOAT_COLUMNS = {"damage_per_min", "damage_share", "vision_per_min", "earned_gpm", "cs_per_min"}


@dataclass
class LoadStats:
    games: int
    skipped_games: int
    series: int


def load_file(conn: psycopg.Connection, path: Path) -> LoadStats:
    raw = _read(path)
    _load_raw(conn, raw)
    df = _prepare(raw)

    team_rows = df[df["position"] == "team"]
    player_rows = df[df["position"].isin(POSITIONS)]

    complete = team_rows.groupby("gameid")["side"].nunique().eq(2)
    complete = complete[complete].index
    team_rows = team_rows[team_rows["gameid"].isin(complete)]
    player_rows = player_rows[player_rows["gameid"].isin(complete)]

    team_ids = _resolve(conn, "team", _external_ids(team_rows, "teamid", "teamname"))
    player_ids = _resolve(conn, "player", _external_ids(player_rows, "playerid", "playername"))
    team_rows = team_rows.assign(team_id=team_rows["team_key"].map(team_ids))
    player_rows = player_rows.assign(
        team_id=player_rows["team_key"].map(team_ids),
        player_id=player_rows["player_key"].map(player_ids),
    )

    games = _games(team_rows)
    team_rows = team_rows[team_rows["gameid"].isin(games["game_id"])]
    player_rows = player_rows[player_rows["gameid"].isin(games["game_id"])]
    _upsert_games(conn, games)
    _replace_stats(conn, games["game_id"].tolist(), team_rows, player_rows)
    series = _upsert_series(conn, games)

    return LoadStats(games=len(games), skipped_games=df["gameid"].nunique() - len(games), series=series)


def _read(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False, dtype={"gameid": str, "patch": str})
    df = df[df["gameid"].notna()].drop_duplicates(["gameid", "participantid"], keep="last")
    df["gameid"] = df["gameid"].astype(str)
    return df


def _prepare(raw: pd.DataFrame) -> pd.DataFrame:
    # Narrowing to the columns we use keeps pandas from fragmenting on the 160+ source columns,
    # and reindex tolerates columns that older seasons don't have.
    df = raw.reindex(columns=SOURCE_COLUMNS)
    return df.assign(
        side=df["side"].str.lower(),
        played_at=pd.to_datetime(df["date"], utc=True),
        team_key=_key(df, "teamid", "teamname"),
        player_key=_key(df, "playerid", "playername"),
    )


def _key(df: pd.DataFrame, id_col: str, name_col: str) -> pd.Series:
    # Older seasons and some leagues lack stable IDs; fall back to the name so the row is still usable.
    names = "name:" + df[name_col].astype("string")
    return df[id_col].astype("string").fillna(names)


def _external_ids(rows: pd.DataFrame, id_col: str, name_col: str) -> dict[str, str]:
    key = "team_key" if id_col == "teamid" else "player_key"
    pairs = rows[[key, name_col]].dropna().drop_duplicates(key, keep="last")
    return dict(zip(pairs[key], pairs[name_col]))


def _resolve(conn: psycopg.Connection, kind: str, names_by_key: dict[str, str]) -> dict[str, int]:
    table, sources, id_col, name_col = {
        "team": ("core.teams", "core.team_sources", "team_id", "name"),
        "player": ("core.players", "core.player_sources", "player_id", "handle"),
    }[kind]

    rows = conn.execute(
        f"SELECT external_id, {id_col} FROM {sources} WHERE source = %s AND external_id = ANY(%s)",
        (SOURCE, list(names_by_key)),
    ).fetchall()
    ids = dict(rows)

    for key, name in names_by_key.items():
        if key in ids:
            continue
        (new_id,) = conn.execute(
            f"INSERT INTO {table} (title, {name_col}) VALUES (%s, %s) RETURNING id", (TITLE, name)
        ).fetchone()
        conn.execute(
            f"INSERT INTO {sources} ({id_col}, source, external_id) VALUES (%s, %s, %s)",
            (new_id, SOURCE, key),
        )
        ids[key] = new_id

    return ids


def _load_raw(conn: psycopg.Connection, df: pd.DataFrame) -> None:
    raw = df.astype(object).where(df.notna(), None)

    with conn.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE raw_in (game_id text, participant_id smallint, data jsonb) ON COMMIT DROP"
        )
        with cur.copy("COPY raw_in (game_id, participant_id, data) FROM STDIN") as copy:
            for record in raw.to_dict("records"):
                copy.write_row((record["gameid"], int(record["participantid"]), Jsonb(record)))
        cur.execute("""
            INSERT INTO lol.raw_oracles_elixir (game_id, participant_id, data)
            SELECT game_id, participant_id, data FROM raw_in
            ON CONFLICT (game_id, participant_id)
            DO UPDATE SET data = EXCLUDED.data, loaded_at = now()
        """)


def _games(team_rows: pd.DataFrame) -> pd.DataFrame:
    blue = team_rows[team_rows["side"] == "blue"].set_index("gameid")
    red = team_rows[team_rows["side"] == "red"].set_index("gameid")

    games = pd.DataFrame({
        "game_id": blue.index,
        "league": blue["league"],
        "year": blue["year"].astype(int),
        "split": blue["split"],
        "playoffs": blue["playoffs"].astype(bool),
        "played_at": blue["played_at"],
        "game_number": blue["game"],
        "patch": blue["patch"].astype("string"),
        "blue_team_id": blue["team_id"],
        "red_team_id": red["team_id"].reindex(blue.index),
        "winner_side": blue["result"].map({1: "blue", 0: "red"}),
        "duration_s": blue["gamelength"],
        "data_completeness": blue["datacompleteness"],
    }).dropna(subset=["blue_team_id", "red_team_id", "winner_side"])
    # Unregistered teams share a placeholder name in the source, so both sides can resolve to the same team.
    return games[games["blue_team_id"] != games["red_team_id"]].reset_index(drop=True)


def _upsert_games(conn: psycopg.Connection, games: pd.DataFrame) -> None:
    columns = list(games.columns)
    placeholders = ", ".join(["%s"] * len(columns))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "game_id")
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO lol.games ({", ".join(columns)}) VALUES ({placeholders})
            ON CONFLICT (game_id) DO UPDATE SET {updates}
            """,
            _tuples(games, ints={"year", "game_number", "blue_team_id", "red_team_id", "duration_s"}),
        )


def _replace_stats(
    conn: psycopg.Connection, game_ids: list[str], team_rows: pd.DataFrame, player_rows: pd.DataFrame
) -> None:
    teams = team_rows.rename(columns=TEAM_STAT_COLUMNS)
    teams = teams.assign(
        game_id=teams["gameid"],
        won=teams["result"].astype(bool),
        bans=teams[[f"ban{i}" for i in range(1, 6)]].apply(lambda r: [b for b in r if pd.notna(b)], axis=1),
    )
    team_cols = ["game_id", "side", "team_id", "won", *TEAM_STAT_COLUMNS.values(), "bans"]

    players = player_rows.rename(columns=PLAYER_STAT_COLUMNS)
    players = players[players["player_id"].notna()].assign(game_id=players["gameid"])
    player_cols = ["game_id", "side", "position", "player_id", "team_id", "champion", *PLAYER_STAT_COLUMNS.values()]

    with conn.cursor() as cur:
        cur.execute("DELETE FROM lol.player_stats WHERE game_id = ANY(%s)", (game_ids,))
        cur.execute("DELETE FROM lol.team_stats WHERE game_id = ANY(%s)", (game_ids,))
        cur.executemany(
            f"INSERT INTO lol.team_stats ({', '.join(team_cols)}) VALUES ({', '.join(['%s'] * len(team_cols))})",
            _tuples(_ensure(teams, team_cols), ints=set(team_cols) - FLAG_COLUMNS - {"game_id", "side", "won", "bans"},
                    flags=FLAG_COLUMNS),
        )
        cur.executemany(
            f"INSERT INTO lol.player_stats ({', '.join(player_cols)}) VALUES ({', '.join(['%s'] * len(player_cols))})",
            _tuples(_ensure(players, player_cols),
                    ints=set(player_cols) - FLOAT_COLUMNS - {"game_id", "side", "position", "champion"}),
        )


def _upsert_series(conn: psycopg.Connection, games: pd.DataFrame) -> int:
    g = games.copy()
    g["team1_id"] = g[["blue_team_id", "red_team_id"]].min(axis=1)
    g["team2_id"] = g[["blue_team_id", "red_team_id"]].max(axis=1)
    g["winner_id"] = g["blue_team_id"].where(g["winner_side"] == "blue", g["red_team_id"])
    g = g.sort_values(["league", "team1_id", "team2_id", "played_at"])

    gap = g.groupby(["league", "team1_id", "team2_id"])["played_at"].diff()
    g["series"] = (gap.isna() | (gap > SERIES_GAP) | g["game_number"].eq(1)).cumsum()

    series = g.groupby("series").agg(
        external_id=("game_id", "first"),
        league=("league", "first"),
        start_time=("played_at", "min"),
        team1_id=("team1_id", "first"),
        team2_id=("team2_id", "first"),
        team1_score=("winner_id", lambda w: int((w == g.loc[w.index, "team1_id"]).sum())),
        team2_score=("winner_id", lambda w: int((w == g.loc[w.index, "team2_id"]).sum())),
    )
    top = series[["team1_score", "team2_score"]].max(axis=1)
    series["best_of"] = 2 * top - 1
    series["winner_id"] = series["team1_id"].where(series["team1_score"] > series["team2_score"])
    series["winner_id"] = series["winner_id"].fillna(
        series["team2_id"].where(series["team2_score"] > series["team1_score"])
    )

    with conn.cursor() as cur:
        match_ids = {}
        for s in series.itertuples():
            (match_id,) = cur.execute(
                """
                INSERT INTO core.matches (title, source, external_id, league, start_time, best_of,
                                          team1_id, team2_id, team1_score, team2_score, winner_id, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'finished')
                ON CONFLICT (source, external_id) DO UPDATE SET
                    start_time = EXCLUDED.start_time,
                    best_of = EXCLUDED.best_of,
                    team1_score = EXCLUDED.team1_score,
                    team2_score = EXCLUDED.team2_score,
                    winner_id = EXCLUDED.winner_id,
                    status = EXCLUDED.status,
                    updated_at = now()
                RETURNING id
                """,
                (TITLE, SOURCE, s.external_id, s.league, s.start_time, int(s.best_of),
                 int(s.team1_id), int(s.team2_id), s.team1_score, s.team2_score,
                 None if pd.isna(s.winner_id) else int(s.winner_id)),
            ).fetchone()
            match_ids[s.Index] = match_id

        cur.executemany(
            "UPDATE lol.games SET match_id = %s WHERE game_id = %s",
            [(match_ids[sid], gid) for gid, sid in zip(g["game_id"], g["series"])],
        )

    return len(series)


def _ensure(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return df.reindex(columns=columns)


def _tuples(df: pd.DataFrame, ints: set[str] = frozenset(), flags: set[str] = frozenset()) -> list[tuple]:
    def convert(column: str, value):
        if isinstance(value, list):
            return value
        if pd.isna(value):
            return None
        if column in flags:
            return bool(value)
        if column in ints:
            return int(value)
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        if hasattr(value, "item"):
            return value.item()
        return value

    columns = list(df.columns)
    return [tuple(convert(c, v) for c, v in zip(columns, row)) for row in df.itertuples(index=False)]
