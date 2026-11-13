"""Snapshots published League of Legends lineups and ships each change to the server.

Runs on a collector host with a residential address: Cloudflare challenges requests from data-centre
ASNs, which rules out the server itself. Each source keeps only its lineup content, and only when it
differs from that source's previous snapshot, so unchanged pages cost no storage. Snapshots are stored
raw and parsed on the server, so a parser fix can be replayed over the full history. Stdlib only, so the
host needs nothing beyond python3 and rsync.
"""
import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

log = logging.getLogger("fetch-lineups")

USER_AGENT = "git-rich lineup collector (personal, non-commercial; checks every 30 minutes)"
NTFY_SERVER = "https://ntfy.sh"
# A source this many runs in a row without a result is broken rather than briefly unreachable.
FAILURE_LIMIT = 3
# More snapshots than this in a day means something volatile slipped into a source's extract: real
# lineups change a few times a day at most.
CHURN_LIMIT = 20


def rotowire(page: str) -> str:
    """The match boxes. The block is cut by its own closing tag because on days without matches it is
    empty and the tools box after the last match, which ends it otherwise, isn't there."""
    start = page.find('<div class="lineups">')
    if start < 0:
        raise ValueError("no lineup section, so the page layout has probably changed")
    block = balanced_div(page, start)
    tools = block.find('<div class="lineup is-tools">')
    # Cloudflare injects a per-request script, which would make every fetch look like a change.
    return re.sub(r"<script\b.*?</script>", "", block[:tools] if tools > 0 else block, flags=re.S)


# LineStar renders its lineups server-side once, then fills in status, odds and projections with Angular
# from an inline period model. Odds and update stamps move all day, so only the schedule is kept from it.
GAME_FIELDS = ("Id", "DateUtc", "AwayTeamId", "HomeTeamId", "AwayTeamAbrev", "HomeTeamAbrev", "StatusText")


def linestar(page: str) -> str:
    """The server-rendered lineups plus each game's schedule from the period model."""
    start = page.find('<div class="rg-ssr">')
    if start < 0:
        raise ValueError("no server-rendered lineups, so the page layout has probably changed")
    model = re.search(r"window\.fscLayoutData = (\{.*?\});\s*$", page, re.S | re.M)
    if model is None:
        raise ValueError("no period model in the page, so its layout has probably changed")
    games = [{k: g.get(k) for k in GAME_FIELDS} for g in json.loads(model.group(1))["Info"]["GameList"]]
    return f'<script type="application/json" id="games">{json.dumps(games)}</script>\n{balanced_div(page, start)}'


def balanced_div(page: str, start: int) -> str:
    """The div opening at start, through its matching closing tag."""
    depth = 0
    for tag in re.finditer(r"<div\b|</div>", page[start:]):
        depth += 1 if tag.group() == "<div" else -1
        if depth == 0:
            return page[start:start + tag.end()]
    raise ValueError("unbalanced div in the lineups")


@dataclass(frozen=True)
class Source:
    url: str
    extract: Callable[[str], str]


SOURCES = {
    "rotowire": Source("https://www.rotowire.com/daily/esports/lol-lineups.php", rotowire),
    "linestar": Source("https://www.linestarapp.com/DailyDashboard/Sport/LOL/Site/DraftKings", linestar),
}


def fetch(url: str, user_agent: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def save_if_changed(name: str, url: str, content: str, data_dir: Path, now: datetime) -> Path | None:
    digest = hashlib.sha256(content.encode()).hexdigest()
    last = data_dir / f"last-{name}.sha256"
    if last.exists() and last.read_text().strip() == digest:
        return None
    path = data_dir / "outbox" / name / now.strftime("%Y/%m/%d") / f"{now:%Y%m%dT%H%M%SZ}.html.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(f"<!-- fetched {now.isoformat()} from {url} -->\n{content}")
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


class Health:
    """Per-check state across runs, so alerts fire once per problem and day rather than every run."""

    def __init__(self, path: Path, now: datetime):
        self.path, self.now = path, now
        self.state = json.loads(path.read_text()) if path.exists() else {}

    def record(self, check: str, ok: bool, saved: bool = False) -> None:
        entry = self.state.setdefault(check, {"failures": 0, "saves": [], "alerted": {}})
        entry["failures"] = 0 if ok else entry["failures"] + 1
        day_ago = (self.now - timedelta(days=1)).isoformat()
        entry["saves"] = [t for t in entry["saves"] if t > day_ago] + ([self.now.isoformat()] if saved else [])
        if entry["failures"] == FAILURE_LIMIT:
            self.alert(entry, "failing", f"Lineups: {check} failing",
                       f"{check} has failed {FAILURE_LIMIT} runs in a row; see the collector's log.")
        if len(entry["saves"]) > CHURN_LIMIT:
            self.alert(entry, "churn", f"Lineups: {check} saves every run",
                       f"{check} saved {len(entry['saves'])} snapshots in 24 hours, so something that changes "
                       "on every fetch has probably slipped into its extract.")

    def alert(self, entry: dict, kind: str, title: str, message: str) -> None:
        today = self.now.date().isoformat()
        if entry["alerted"].get(kind) == today:
            return
        entry["alerted"][kind] = today
        log.warning("%s", message)
        notify(title, message)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state))


def notify(title: str, message: str) -> None:
    """Best effort, and off unless NTFY_TOPIC is set: an alert that can't be delivered is only logged."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    body = {"topic": topic, "title": title, "message": message, "priority": 4, "tags": ["warning"]}
    request = urllib.request.Request(NTFY_SERVER, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=10).close()
    except (urllib.error.URLError, TimeoutError) as e:
        log.warning("alert not sent: %s", getattr(e, "reason", e))


def main() -> None:
    parser = argparse.ArgumentParser(prog="fetch-lineups", description=__doc__.splitlines()[0])
    parser.add_argument("--server", required=True, help="user@host the snapshots are sent to")
    parser.add_argument("--key", type=Path, required=True, help="SSH key the server limits to its lineup folder")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".local/share/git-rich-lineups")
    parser.add_argument("--sources", default=",".join(SOURCES), help=f"comma-separated, from {', '.join(SOURCES)}")
    parser.add_argument("--user-agent", default=USER_AGENT)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    health = Health(args.data_dir / "health.json", now)
    failed = False
    # One source failing, from a block or a layout change, must not stop the others.
    for name in args.sources.split(","):
        source = SOURCES[name]
        try:
            content = source.extract(fetch(source.url, args.user_agent))
        except urllib.error.HTTPError as e:
            log.error("%s: HTTP %d", name, e.code)
            failed = True
            health.record(name, ok=False)
            continue
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            log.error("%s: %s", name, e)
            failed = True
            health.record(name, ok=False)
            continue
        saved = save_if_changed(name, source.url, content, args.data_dir, now)
        log.info("%s: saved %s", name, saved.name if saved else "nothing, lineups unchanged")
        health.record(name, ok=True, saved=saved is not None)

    try:
        ship(args.data_dir, args.server, args.key)
        health.record("sending", ok=True)
    except subprocess.CalledProcessError as e:
        log.error("sending to %s failed (rsync exit %d), will retry next run", args.server, e.returncode)
        failed = True
        health.record("sending", ok=False)
    health.save()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
