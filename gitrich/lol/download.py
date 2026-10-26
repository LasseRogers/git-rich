from pathlib import Path

import gdown
from gdown.exceptions import FileURLRetrievalError

FOLDER_ID = "1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH"


class QuotaExceeded(Exception):
    pass


def download_years(years: list[int], dest: Path) -> list[Path]:
    # File IDs change when Oracle's Elixir replaces a year's file, so resolve them from the folder listing.
    listing = gdown.download_folder(id=FOLDER_ID, skip_download=True, quiet=True, retries=3)
    files = {
        int(Path(f.path).name[:4]): f
        for f in listing
        if Path(f.path).name[:4].isdigit() and f.path.endswith(".csv")
    }

    missing = [y for y in years if y not in files]
    if missing:
        raise LookupError(f"No Oracle's Elixir file for {missing}, available: {sorted(files)}")

    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for year in years:
        file = files[year]
        out = dest / Path(file.path).name
        try:
            gdown.download(id=file.id, output=str(out), quiet=True, retries=3)
        except FileURLRetrievalError as e:
            # Drive throttles popular public files; the browser usually still works.
            raise QuotaExceeded(
                f"Google Drive refused {out.name}. Download it from "
                f"https://drive.google.com/uc?id={file.id} and load it with --file."
            ) from e
        paths.append(out)
    return paths
