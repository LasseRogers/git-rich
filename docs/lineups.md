# Lineup snapshots

The model rates teams by their players but has to assume each team fields the lineup of its last match. In the test seasons that assumption was wrong in a quarter of matches, and knowing the real lineup would lower the log loss by about 0.007. Two sites publish lineups ahead of matches, and `lineups/fetch_lineups.py` records both to measure how early and how reliably they arrive:

| Source | Coverage | What a snapshot holds |
|---|---|---|
| `rotowire` | LPL, LCK, LEC and LCS on match days, as expected and then starting lineups | The page's list of match boxes |
| `linestar` | Every match with a DraftKings slate, including internationals | The server-rendered lineups, plus each game's ID, UTC start and teams from the page's period model |

LineStar fills in its expected or confirmed flag client-side, so its snapshots carry the lineup but not the flag.

This is data collection only. Nothing reads the snapshots yet; they get evaluated before anything goes into the model.

## How it works

RotoWire sits behind Cloudflare, which challenges requests from data-centre ASNs, so the server can't fetch the page itself. Collection runs on a separate collector host on a residential connection, which fetches each source every 30 minutes and pushes changes to the server over SSH.

Each run keeps only a source's lineup content, gzipped, and only when it differs from that source's previous snapshot. Snapshots land in `~/lineups/incoming/<source>/YYYY/MM/DD/` on the server, named by UTC fetch time. A failing source doesn't stop the others, and a snapshot that fails to send stays on the collector host and goes out with the next run. `--sources` limits a run to some of them.

Both sites' `robots.txt` allow these pages. The collector keeps a light footprint: one page per source every 30 minutes, a descriptive user agent, and the data stays private to this project.

## Server

Create the drop folder and allow the collector's key to write into it and nothing else:

```bash
mkdir -p ~/lineups/incoming
echo 'command="/usr/bin/rrsync -wo /home/ubuntu/lineups/incoming",restrict <the collector public key>' >> ~/.ssh/authorized_keys
```

`rrsync -wo` confines the key to writing into that folder; `restrict` removes the shell, forwarding and everything else an SSH login normally allows.

## Collector host

Any always-on Linux machine on a residential connection with Python 3.10 or newer, `rsync` and systemd. Make a key without a passphrase, since the timer uses it unattended, and add its public half on the server as above:

```bash
ssh-keygen -t ed25519 -N "" -C "lineup-collector" -f ~/.ssh/git_rich_lineups
```

The host only needs the collector, so a sparse clone keeps the rest of the repository off its disk. Run the collector once by hand, then install the timer:

```bash
git clone --filter=blob:none --sparse https://github.com/LasseRogers/git-rich.git && cd git-rich
git sparse-checkout set lineups
python3 lineups/fetch_lineups.py --server ubuntu@<server> --key ~/.ssh/git_rich_lineups
lineups/install-lineups-timer.sh ubuntu@<server>
```

`systemctl --user status git-rich-lineups.service` shows the last run and its output. Update with `git pull`; the timer picks up the new code on its next run.
