"""Backfills OddsPapi odds history for finished LoL fixtures into the odds-data branch. Stdlib only, like collect.py."""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gitrich.odds.collect import MARKETS, ApiError, BudgetExhausted, Client, _read_json, _write_json

log = logging.getLogger("collect-history")

# OddsPapi's per-endpoint cooldowns, longer than the client's general one. A rate-limited retry still costs a request.
LISTING_COOLDOWN = 2.0
HISTORY_COOLDOWN = 5.0
LISTING_MAX_AGE = timedelta(days=7)
FIXTURE_FIELDS = ("fixtureId", "tournamentId", "tournamentName", "startTime",
                  "participant1Id", "participant1Name", "participant2Id", "participant2Name")


def finished_fixtures(client: Client, out: Path, tournament_ids: list[int], since: str, now: datetime) -> list[dict]:
    """Finished fixtures. Listings are cached, so a backfill spread over several runs pays once.

    hasOdds only reflects current prices, so it can't narrow finished fixtures to the ones Pinnacle priced.
    """
    fixtures = {}
    for tournament_id in tournament_ids:
        path = out / "history" / "fixtures" / f"{tournament_id}.json"
        cached = _read_json(path, None)
        if cached and now - datetime.fromisoformat(cached["fetchedAt"]) < LISTING_MAX_AGE:
            data = cached["data"]
        else:
            time.sleep(LISTING_COOLDOWN)
            try:
                data = client.get("fixtures", tournamentId=tournament_id, statusId=2, **{"from": since})
            except ApiError as e:
                if "FIXTURE_NOT_FOUND" not in str(e):
                    raise
                data = []
            _write_json(path, {"fetchedAt": now.isoformat(), "data": data})
        log.info("tournament %s: %d finished fixtures", tournament_id, len(data))
        fixtures.update((f["fixtureId"], f) for f in data)
    return list(fixtures.values())


def trim(history: dict) -> dict:
    """Price timelines per bookmaker, market and outcome, oldest first, for the markets collect.py keeps."""
    books = {}
    for slug, book in (history.get("bookmakers") or {}).items():
        markets = {}
        for market_id, market in (book.get("markets") or {}).items():
            if market_id not in MARKETS:
                continue
            outcomes = {}
            for outcome_id, outcome in (market.get("outcomes") or {}).items():
                entries = (outcome.get("players") or {}).get("0") or []
                timeline = [{"at": e["createdAt"], "price": e["price"], "active": e.get("active")}
                            for e in entries if e.get("price")]
                if timeline:
                    outcomes[outcome_id] = sorted(timeline, key=lambda e: e["at"])
            if outcomes:
                markets[market_id] = outcomes
        if markets:
            books[slug] = markets
    return books


def backfill(client: Client, out: Path, tournament_ids: list[int], bookmakers: str, since: str,
             limit: int, now: datetime) -> None:
    fixtures = finished_fixtures(client, out, tournament_ids, since, now)
    done = out / "history" / "odds"
    # Oldest first: the regular seasons come before the off-season events at the end of the year.
    todo = sorted((f for f in fixtures if not (done / f"{f['fixtureId']}.json").exists()),
                  key=lambda f: f["startTime"])
    log.info("%d finished fixtures, %d without history, fetching up to %d", len(fixtures), len(todo), limit)

    for fixture in todo[:limit]:
        time.sleep(HISTORY_COOLDOWN)
        history = client.get("historical-odds", fixtureId=fixture["fixtureId"], bookmakers=bookmakers)
        # Written even when empty: the request is spent either way.
        _write_json(done / f"{fixture['fixtureId']}.json",
                    {"fixture": {k: fixture.get(k) for k in FIXTURE_FIELDS}, "bookmakers": trim(history)})
        log.info("%s %s vs %s", fixture["startTime"][:10],
                 fixture.get("participant1Name"), fixture.get("participant2Name"))


def main() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    parser = argparse.ArgumentParser(prog="collect-history")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tournament", type=int, action="append", required=True)
    parser.add_argument("--bookmakers", default="pinnacle,bet365", help="comma-separated, at most three")
    parser.add_argument("--since", default=f"{now.year}-01-01T00:00:00Z")
    parser.add_argument("--max", type=int, default=100, help="most fixtures to fetch this run")
    parser.add_argument("--budget", type=int, default=220,
                        help="max requests per calendar month, shared with collect-odds")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    key = os.environ.get("ODDSPAPI_KEY")
    if not key:
        sys.exit("ODDSPAPI_KEY is not set")

    client = Client(key, args.out / "usage" / f"{now:%Y-%m}.json", args.budget)
    try:
        backfill(client, args.out, args.tournament, args.bookmakers, args.since, args.max, now)
    except BudgetExhausted as e:
        log.warning("%s, stopping", e)
    except ApiError as e:
        log.error("%s", e)
        sys.exit(1)
    log.info("%d requests used this month", client.usage["requests"])


if __name__ == "__main__":
    main()
