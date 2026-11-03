"""Snapshots RotoWire's League of Legends lineups page and ships each change to the server.

Runs on a Raspberry Pi at home, because RotoWire's Cloudflare turns away the cloud server's address.
It stores only the page's lineup section, and only when that has changed, so a quiet day writes nothing.
Reading players out of the snapshots happens later on the server, so the raw copies stay re-readable.
Stdlib only: the Pi needs no packages beyond python3 and rsync.
"""
import argparse
import gzip
import hashlib
import logging
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("fetch-lineups")

URL = "https://www.rotowire.com/daily/esports/lol-lineups.php"
USER_AGENT = "git-rich lineup collector (personal, non-commercial; checks every 30 minutes)"
START = '<div class="lineups">'
# The tools box closes the list of matches; everything after it is ads and navigation.
END = '<div class="lineup is-tools">'


def lineup_section(page: str) -> str:
    start = page.find(START)
    if start < 0:
        raise ValueError("no lineup section in the page, so its layout has probably changed")
    end = page.find(END, start)
    return page[start:end if end > 0 else len(page)]


def fetch(url: str, user_agent: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def save_if_changed(section: str, data_dir: Path, now: datetime) -> Path | None:
    digest = hashlib.sha256(section.encode()).hexdigest()
    last = data_dir / "last.sha256"
    if last.exists() and last.read_text().strip() == digest:
        return None
    path = data_dir / "outbox" / now.strftime("%Y/%m/%d") / f"{now:%Y%m%dT%H%M%SZ}.html.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(f"<!-- fetched {now.isoformat()} from {URL} -->\n{section}")
    last.write_text(digest)
    return path


def ship(data_dir: Path, server: str, key: Path) -> None:
    """Moves everything in the outbox to the server. A file that fails to send stays for the next run."""
    outbox = data_dir / "outbox"
    if not any(outbox.rglob("*.html.gz")):
        return
    ssh = f"ssh -i {key} -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=30"
    # The server's key only allows writing into its lineup folder, so the destination is relative to that.
    subprocess.run(["rsync", "-a", "--remove-source-files", "-e", ssh, f"{outbox}/", f"{server}:"], check=True)
    for folder in sorted((p for p in outbox.rglob("*") if p.is_dir()), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()


def main() -> None:
    parser = argparse.ArgumentParser(prog="fetch-lineups", description=__doc__.splitlines()[0])
    parser.add_argument("--server", required=True, help="user@host the snapshots are sent to")
    parser.add_argument("--key", type=Path, required=True, help="SSH key the server limits to its lineup folder")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".local/share/git-rich-lineups")
    parser.add_argument("--user-agent", default=USER_AGENT)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        section = lineup_section(fetch(URL, args.user_agent))
    except urllib.error.HTTPError as e:
        # 403 is Cloudflare's bot check; it says nothing about the page, so there is no point retrying now.
        log.error("RotoWire answered HTTP %d", e.code)
        sys.exit(1)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        log.error("%s", e)
        sys.exit(1)

    saved = save_if_changed(section, args.data_dir, now)
    log.info("saved %s", saved.name if saved else "nothing, lineups unchanged")
    try:
        ship(args.data_dir, args.server, args.key)
    except subprocess.CalledProcessError as e:
        log.error("sending to %s failed (rsync exit %d), will retry next run", args.server, e.returncode)
        sys.exit(1)


if __name__ == "__main__":
    main()
