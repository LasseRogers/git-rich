import argparse
import logging
from pathlib import Path

from gitrich.db import connect
from gitrich.odds.link import link
from gitrich.odds.load import load_dir


def main() -> None:
    parser = argparse.ArgumentParser(prog="ingest-odds", description="Load odds snapshots from the odds-data branch.")
    parser.add_argument("root", type=Path, nargs="?", default=Path("/odds"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with connect() as conn:
        loaded = load_dir(conn, args.root)
        linked = link(conn)

    logging.info("%d files, %d events, %d prices", loaded.files, loaded.events, loaded.prices)
    logging.info("%d teams mapped, %d events linked to matches", linked.teams, linked.matches)
    if linked.unmapped:
        logging.warning("unmapped teams, add them to team_aliases.csv: %s", ", ".join(linked.unmapped))


if __name__ == "__main__":
    main()
