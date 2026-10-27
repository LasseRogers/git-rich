import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from psycopg.types.json import Jsonb

from gitrich.api.predictor import MODEL_NAME, Predictor
from gitrich.db import connect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Markets only offered on series longer than one game. A Bo3 and a Bo5 look the same here.
MULTI_MAP_MARKETS = ("map3_winner", "maps_over_under_2.5", "maps_handicap_-1.5", "maps_handicap_+1.5")

predictor = Predictor()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Replaying every game takes a while; serve /health meanwhile instead of blocking startup.
    threading.Thread(target=predictor.load, daemon=True).start()
    yield


app = FastAPI(title="git-rich", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    model = predictor.model
    return {
        "ready": predictor.ready,
        "model_version": model.version if model else None,
        "games": predictor.games,
        "loaded_at": predictor.loaded_at,
    }


@app.post("/reload")
def reload() -> dict:
    predictor.load()
    return health()


@app.get("/predict")
def predict(team1_id: int, team2_id: int) -> dict:
    _require_ready()
    with connect() as conn:
        names = _names(conn, "core.teams", "name", [team1_id, team2_id])
        if len(names) < 2:
            raise HTTPException(404, "unknown team")
        pred = predictor.predict(team1_id, team2_id, datetime.now(timezone.utc))
        players = _names(conn, "core.players", "handle", pred["lineup_team1"] + pred["lineup_team2"])
    return {
        "team1": {"id": team1_id, "name": names[team1_id], "lineup": [players.get(p) for p in pred["lineup_team1"]]},
        "team2": {"id": team2_id, "name": names[team2_id], "lineup": [players.get(p) for p in pred["lineup_team2"]]},
        "p_team1_by_format": pred["p_team1"],
        "features": pred["features"],
    }


@app.get("/upcoming")
def upcoming(hours: int = Query(72, ge=1, le=24 * 14)) -> dict:
    _require_ready()
    version = predictor.model.version
    out = []
    with connect() as conn:
        events = conn.execute(
            """
            SELECT e.id, e.tournament, e.start_time, e.home_team_id, e.away_team_id, h.name, a.name,
                   coalesce(bool_or(s.market = ANY(%s)), false)
            FROM core.odds_events e
            JOIN core.teams h ON h.id = e.home_team_id
            JOIN core.teams a ON a.id = e.away_team_id
            LEFT JOIN core.odds_snapshots s ON s.odds_event_id = e.id
            WHERE e.start_time > now() AND e.start_time < now() + make_interval(hours => %s)
            GROUP BY e.id, h.name, a.name
            ORDER BY e.start_time
            """,
            (list(MULTI_MAP_MARKETS), hours),
        ).fetchall()

        for event_id, tournament, start, team1, team2, name1, name2, multi_map in events:
            pred = predictor.predict(team1, team2, start)
            best_of = 3 if multi_map else 1
            p = pred["p_team1"][best_of]
            conn.execute(
                """
                INSERT INTO core.predictions
                    (odds_event_id, team1_id, team2_id, best_of, p_team1, model_name, model_version, features)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (odds_event_id, model_name, model_version) DO NOTHING
                """,
                (event_id, team1, team2, best_of, p, MODEL_NAME, version, Jsonb(pred["features"])),
            )
            players = _names(conn, "core.players", "handle", pred["lineup_team1"] + pred["lineup_team2"])
            out.append({
                "odds_event_id": event_id,
                "tournament": tournament,
                "start_time": start,
                "team1": {"id": team1, "name": name1, "lineup": [players.get(p) for p in pred["lineup_team1"]]},
                "team2": {"id": team2, "name": name2, "lineup": [players.get(p) for p in pred["lineup_team2"]]},
                "best_of": best_of,
                "p_team1": p,
                "p_team1_by_format": pred["p_team1"],
            })
    return {"model_version": version, "matches": out}


def _require_ready() -> None:
    if not predictor.ready:
        raise HTTPException(503, "model not loaded yet")


def _names(conn, table: str, column: str, ids: list[int]) -> dict[int, str]:
    rows = conn.execute(f"SELECT id, {column} FROM {table} WHERE id = ANY(%s)", (ids,)).fetchall()
    return dict(rows)

