import argparse
import logging
import sys
import tempfile
from pathlib import Path

from gitrich.db import connect
from gitrich.lol.download import Drive, MissingCredentials, SourceFile
from gitrich.lol.load import load_file

log = logging.getLogger("ingest-lol")


def load(path: Path, source: SourceFile | None = None) -> None:
    # One transaction per file: a failed load leaves that year, and its recorded version, untouched.
    with connect() as conn:
        stats = load_file(conn, path)
        if source:
            conn.execute(
                """
                INSERT INTO lol.source_files (name, modified_at) VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET modified_at = EXCLUDED.modified_at, loaded_at = now()
                """,
                (source.name, source.modified_at),
            )
    log.info("%s: %d games, %d series, %d incomplete games skipped",
             path.name, stats.games, stats.series, stats.skipped_games)


def changed(files: list[SourceFile]) -> list[SourceFile]:
    with connect() as conn:
        loaded = dict(conn.execute("SELECT name, modified_at FROM lol.source_files").fetchall())
    return [f for f in files if f.name not in loaded or f.modified_at > loaded[f.name]]


def main() -> None:
    parser = argparse.ArgumentParser(prog="ingest-lol", description="Load Oracle's Elixir match data.")
    parser.add_argument("years", nargs="*", type=int,
                        help="years to reload; by default every file that changed since it was last loaded")
    parser.add_argument("--file", type=Path, action="append", help="load a local CSV instead of downloading")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.file:
        for path in args.file:
            load(path)
        return

    try:
        drive = Drive()
    except MissingCredentials as e:
        sys.exit(str(e))
    files = drive.files()

    if args.years:
        missing = set(args.years) - {f.year for f in files}
        if missing:
            sys.exit(f"No Oracle's Elixir file for {sorted(missing)}, available: {sorted(f.year for f in files)}")
        todo = [f for f in files if f.year in args.years]
    else:
        todo = changed(files)

    if not todo:
        log.info("match data is up to date")
        return

    log.info("loading %s", ", ".join(f.name[:4] for f in todo))
    with tempfile.TemporaryDirectory() as tmp:
        for file in todo:
            path = drive.download(file, Path(tmp))
            load(path, file)
            path.unlink()


if __name__ == "__main__":
    main()
