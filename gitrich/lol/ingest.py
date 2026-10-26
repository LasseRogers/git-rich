import argparse
import logging
import sys
import tempfile
from datetime import date
from pathlib import Path

from gitrich.db import connect
from gitrich.lol.download import QuotaExceeded, download_years
from gitrich.lol.load import load_file

log = logging.getLogger("ingest-lol")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ingest-lol", description="Load Oracle's Elixir match data.")
    parser.add_argument("years", nargs="*", type=int, default=[date.today().year])
    parser.add_argument("--file", type=Path, action="append", help="load a local CSV instead of downloading")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with tempfile.TemporaryDirectory() as tmp:
        if args.file:
            paths = args.file
        else:
            log.info("downloading %s", args.years)
            try:
                paths = download_years(args.years, Path(tmp))
            except QuotaExceeded as e:
                log.error("%s", e)
                sys.exit(2)

        for path in paths:
            # One transaction per file: a failed load leaves that year untouched.
            with connect() as conn:
                stats = load_file(conn, path)
            log.info(
                "%s: %d games, %d series, %d incomplete games skipped",
                path.name, stats.games, stats.series, stats.skipped_games,
            )


if __name__ == "__main__":
    main()
