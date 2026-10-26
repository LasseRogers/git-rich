"""Snapshots OddsPapi LoL odds for the odds-data branch. Stdlib only, so CI needs no install."""
import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("collect-odds")

API = "https://api.oddspapi.io/v4"
SPORT_ID = 18

# Series winner, total maps, map handicaps, map 1-3 winners. Props are dropped to keep the branch small.
MARKETS = {"181", "183", "1825", "1837", "1847", "1849", "1851"}
OUTCOME_FIELDS = ("price", "active", "changedAt", "limit", "mainLine")

REFERENCE_MAX_AGE = timedelta(hours=20)


class BudgetExhausted(Exception):
    pass


class ApiError(Exception):
    pass


class Client:
    def __init__(self, key: str, usage_path: Path, budget: int):
        self.key = key
        self.usage_path = usage_path
        self.budget = budget
        self.usage = _read_json(usage_path, {"requests": 0})
        self._last_call = 0.0

    def get(self, path: str, **params):
        if self.usage["requests"] >= self.budget:
            raise BudgetExhausted(f"{self.usage['requests']}/{self.budget} requests used this month")

        # Documented cooldown is 1s per endpoint.
        time.sleep(max(0.0, 1.1 - (time.monotonic() - self._last_call)))
        url = f"{API}/{path}?{urllib.parse.urlencode({**params, 'apiKey': self.key})}"
        self.usage["requests"] += 1
        _write_json(self.usage_path, self.usage)
        self._last_call = time.monotonic()

        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as e:
            raise ApiError(f"{path}: HTTP {e.code} {e.read()[:500]!r}") from e

        if isinstance(body, dict) and "error" in body:
            raise ApiError(f"{path}: {body['error']}")
        return body


def collect(client: Client, out: Path, bookmakers: list[str], now: datetime) -> None:
    tournaments = _reference(client, out / "reference" / "tournaments.json", now, "tournaments", sportId=SPORT_ID)
    active = [
        t["tournamentId"]
        for t in tournaments
        if t.get("futureFixtures", 0) + t.get("upcomingFixtures", 0) + t.get("liveFixtures", 0) > 0
    ]
    if not active:
        log.info("no active tournaments")
        return

    participants_path = out / "reference" / "participants.json"
    participants = _read_json(participants_path, {}).get("data", {})
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    for bookmaker in bookmakers:
        fixtures = client.get(
            "odds-by-tournaments",
            tournamentIds=",".join(map(str, active)),
            bookmaker=bookmaker,
        )
        snapshot = [_trim(f, bookmaker) for f in fixtures]
        snapshot = [f for f in snapshot if f["markets"]]

        path = out / "snapshots" / now.strftime("%Y/%m/%d") / f"{stamp}_{bookmaker}.json"
        _write_json(path, {"capturedAt": now.isoformat(), "bookmaker": bookmaker, "fixtures": snapshot})
        log.info("%s: %d fixtures with odds", bookmaker, len(snapshot))

        unknown = {str(p) for f in snapshot for p in (f["participant1Id"], f["participant2Id"])} - participants.keys()
        if unknown:
            log.info("%d unknown participants", len(unknown))
            participants = _reference(client, participants_path, now, "participants", sportId=SPORT_ID)


def _reference(client: Client, path: Path, now: datetime, endpoint: str, **params):
    # Capped at one fetch per window, so a team OddsPapi hasn't listed yet can't drain the budget.
    cached = _read_json(path, None)
    if cached and now - datetime.fromisoformat(cached["fetchedAt"]) < REFERENCE_MAX_AGE:
        return cached["data"]

    data = client.get(endpoint, **params)
    _write_json(path, {"fetchedAt": now.isoformat(), "data": data})
    return data


def _trim(fixture: dict, bookmaker: str) -> dict:
    book = (fixture.get("bookmakerOdds") or {}).get(bookmaker) or {}
    markets = {}
    for market_id, market in (book.get("markets") or {}).items():
        if market_id not in MARKETS:
            continue
        outcomes = {}
        for outcome_id, outcome in (market.get("outcomes") or {}).items():
            player = (outcome.get("players") or {}).get("0")
            if player and player.get("price"):
                outcomes[outcome_id] = {k: player.get(k) for k in OUTCOME_FIELDS}
        if outcomes:
            markets[market_id] = {"active": market.get("marketActive"), "outcomes": outcomes}

    return {
        "fixtureId": fixture["fixtureId"],
        "tournamentId": fixture.get("tournamentId"),
        "participant1Id": fixture.get("participant1Id"),
        "participant2Id": fixture.get("participant2Id"),
        "statusId": fixture.get("statusId"),
        "startTime": fixture.get("startTime"),
        "suspended": book.get("suspended"),
        "markets": markets,
    }


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(prog="collect-odds")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bookmaker", action="append", required=True)
    parser.add_argument("--budget", type=int, default=220, help="max requests per calendar month")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    key = os.environ.get("ODDSPAPI_KEY")
    if not key:
        # Checked before any request, since a keyless call still counts against the quota.
        sys.exit("ODDSPAPI_KEY is not set")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    client = Client(key, args.out / "usage" / f"{now:%Y-%m}.json", args.budget)

    try:
        collect(client, args.out, args.bookmaker, now)
    except BudgetExhausted as e:
        log.warning("%s, skipping", e)
    except ApiError as e:
        log.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
