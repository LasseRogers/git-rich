import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)

SOURCE = "oddspapi"
TITLE = "lol"

# OddsPapi market and outcome IDs, named from participant 1's point of view.
MARKETS = {
    "181": ("winner", {"181": "team1", "182": "team2"}),
    "183": ("maps_over_under_2.5", {"183": "over", "184": "under"}),
    "1825": ("maps_handicap_-1.5", {"1825": "team1", "1826": "team2"}),
    "1837": ("maps_handicap_+1.5", {"1837": "team1", "1838": "team2"}),
    "1847": ("map1_winner", {"1847": "team1", "1848": "team2"}),
    "1849": ("map2_winner", {"1849": "team1", "1850": "team2"}),
    "1851": ("map3_winner", {"1851": "team1", "1852": "team2"}),
}
WINNER = "181"


@dataclass
class LoadStats:
    files: int
    events: int
    prices: int


def load_dir(conn: psycopg.Connection, root: Path) -> LoadStats:
    participants = _reference(root / "reference" / "participants.json", {})
    tournaments = {
        str(t["tournamentId"]): t.get("tournamentName")
        for t in _reference(root / "reference" / "tournaments.json", [])
    }

    files = sorted((root / "snapshots").rglob("*.json"))
    events: dict[str, int] = {}
    prices = 0

    with conn.cursor() as cur:
        for path in files:
            snapshot = json.loads(path.read_text())
            captured_at = datetime.fromisoformat(snapshot["capturedAt"])
            bookmaker = snapshot["bookmaker"]

            for fixture in snapshot["fixtures"]:
                event_id = _upsert_event(cur, fixture, participants, tournaments)
                events[fixture["fixtureId"]] = event_id
                rows = list(_prices(event_id, bookmaker, captured_at, fixture))
                cur.executemany(
                    """
                    INSERT INTO core.odds_snapshots
                        (odds_event_id, bookmaker, market, selection, price, captured_at, changed_at, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (odds_event_id, bookmaker, market, selection, captured_at) DO NOTHING
                    """,
                    rows,
                )
                prices += max(cur.rowcount, 0)

    return LoadStats(files=len(files), events=len(events), prices=prices)


def load_history(conn: psycopg.Connection, root: Path) -> LoadStats:
    """Backfilled price timelines, one file per fixture. Only the winner market, which is what backtests price."""
    market, selections = MARKETS[WINNER]
    files = sorted((root / "history" / "odds").glob("*.json"))
    events = prices = 0

    with conn.cursor() as cur:
        for path in files:
            history = json.loads(path.read_text())
            timelines = [
                (bookmaker, selections[outcome_id], entry)
                for bookmaker, markets in history["bookmakers"].items()
                for outcome_id, timeline in markets.get(WINNER, {}).items() if outcome_id in selections
                for entry in timeline if entry["price"] > 1
            ]
            if not timelines:
                continue

            fixture = history["fixture"]
            participants = {str(fixture[f"participant{i}Id"]): fixture[f"participant{i}Name"] for i in (1, 2)}
            event_id = _upsert_event(cur, fixture, participants,
                                     {str(fixture["tournamentId"]): fixture["tournamentName"]})
            cur.executemany(
                """
                INSERT INTO core.odds_snapshots (odds_event_id, bookmaker, market, selection, price,
                                                 captured_at, changed_at, active, backfilled)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
                ON CONFLICT (odds_event_id, bookmaker, market, selection, captured_at) DO NOTHING
                """,
                [(event_id, bookmaker, market, selection, e["price"], e["at"], e["at"], bool(e["active"]))
                 for bookmaker, selection, e in timelines],
            )
            events += 1
            prices += max(cur.rowcount, 0)

    return LoadStats(files=len(files), events=events, prices=prices)


def _upsert_event(cur: psycopg.Cursor, fixture: dict, participants: dict, tournaments: dict) -> int:
    home_id, away_id = str(fixture["participant1Id"]), str(fixture["participant2Id"])
    (event_id,) = cur.execute(
        """
        INSERT INTO core.odds_events (source, external_id, title, home_name, away_name,
                                      home_participant_id, away_participant_id, start_time, tournament)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, external_id) DO UPDATE SET
            home_name = EXCLUDED.home_name,
            away_name = EXCLUDED.away_name,
            home_participant_id = EXCLUDED.home_participant_id,
            away_participant_id = EXCLUDED.away_participant_id,
            start_time = EXCLUDED.start_time,
            tournament = EXCLUDED.tournament,
            updated_at = now()
        RETURNING id
        """,
        (SOURCE, fixture["fixtureId"], TITLE,
         participants.get(home_id, f"oddspapi:{home_id}"), participants.get(away_id, f"oddspapi:{away_id}"),
         home_id, away_id, fixture["startTime"], tournaments.get(str(fixture.get("tournamentId")))),
    ).fetchone()
    return event_id


def _prices(event_id: int, bookmaker: str, captured_at: datetime, fixture: dict):
    for market_id, market in fixture["markets"].items():
        if market_id not in MARKETS:
            continue
        name, selections = MARKETS[market_id]
        for outcome_id, outcome in market["outcomes"].items():
            selection = selections.get(outcome_id)
            if selection is None or not outcome.get("price") or outcome["price"] <= 1:
                continue
            active = bool(market.get("active")) and bool(outcome.get("active")) and not fixture.get("suspended")
            yield (event_id, bookmaker, name, selection, outcome["price"], captured_at,
                   outcome.get("changedAt"), active)


def _reference(path: Path, default):
    try:
        return json.loads(path.read_text())["data"]
    except FileNotFoundError:
        log.warning("%s missing", path)
        return default
