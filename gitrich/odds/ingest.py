import argparse
import logging
from pathlib import Path

from gitrich.db import connect
from gitrich.odds.load import load_dir


def main() -> None:
    parser = argparse.ArgumentParser(prog="ingest-odds", description="Load odds snapshots from the odds-data branch.")
    parser.add_argument("root", type=Path, nargs="?", default=Path("/odds"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with connect() as conn:
        stats = load_dir(conn, args.root)
    logging.info("%d files, %d events, %d prices", stats.files, stats.events, stats.prices)


if __name__ == "__main__":
    main()
