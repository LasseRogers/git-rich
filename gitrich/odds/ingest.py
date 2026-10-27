import argparse
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from gitrich.betting.settle import settle
from gitrich.db import connect
from gitrich.odds.link import link
from gitrich.odds.load import load_dir, load_history


def paper_trade(api_url: str) -> int | None:
    """Has the API place paper bets on the fresh prices. None if it isn't up."""
    req = urllib.request.Request(f"{api_url}/paper-trade", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.load(resp)["placed"]
    except (urllib.error.URLError, TimeoutError) as e:
        logging.warning("paper bets not placed, API at %s unavailable: %s", api_url, getattr(e, "reason", e))
        return None


def main() -> None:
    parser = argparse.ArgumentParser(prog="ingest-odds", description="Load odds snapshots from the odds-data branch.")
    parser.add_argument("root", type=Path, nargs="?", default=Path("/odds"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with connect() as conn:
        loaded = load_dir(conn, args.root)
        backfilled = load_history(conn, args.root)
        linked = link(conn)
        settled = settle(conn)

    logging.info("%d files, %d events, %d prices", loaded.files, loaded.events, loaded.prices)
    logging.info("history: %d files, %d events, %d prices", backfilled.files, backfilled.events, backfilled.prices)
    logging.info("%d teams mapped, %d events linked to matches, %d bets settled",
                 linked.teams, linked.matches, settled)
    if linked.unmapped:
        logging.warning("unmapped teams, add them to team_aliases.csv: %s", ", ".join(linked.unmapped))

    placed = paper_trade(os.environ.get("API_URL", "http://api:8000"))
    if placed is not None:
        logging.info("%d paper bets placed", placed)


if __name__ == "__main__":
    main()
