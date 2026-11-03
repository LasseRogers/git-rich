# Lineup snapshots

The model rates teams by their players but has to assume each team fields the lineup of its last match. In the test seasons that assumption was wrong in a quarter of matches, and knowing the real lineup would lower the log loss by about 0.007. RotoWire publishes expected and starting lineups for the LPL, LCK, LEC and LCS on match days, so `pi/fetch_lineups.py` records them to find out how early and how reliably they arrive.

This is data collection only. Nothing reads the snapshots yet; they get evaluated before anything goes into the model.

## How it works

A Raspberry Pi at home fetches the lineups page every 30 minutes. RotoWire's Cloudflare turns away the cloud server's address but not a home connection. It keeps the page's lineup section, gzipped, only when it has changed, and sends it to the server with `rsync`. Snapshots land in `~/lineups/incoming/YYYY/MM/DD/` on the server, named by UTC fetch time. A file that fails to send stays on the Pi for the next run.

RotoWire's `robots.txt` allows all pages. The collector stays a light visitor: one page every 30 minutes, an honest user agent, and the data is for this project only, never republished.

## Server

Create the drop folder and allow the Pi's key to write into it and nothing else:

```bash
mkdir -p ~/lineups/incoming
echo 'command="/usr/bin/rrsync -wo /home/ubuntu/lineups/incoming",restrict <the Pi public key>' >> ~/.ssh/authorized_keys
```

## Pi

Any Pi with Python 3.10 or newer and `rsync`. Make a key without a passphrase, since the timer uses it unattended, and add its public half on the server as above:

```bash
ssh-keygen -t ed25519 -N "" -C "pi-lineups" -f ~/.ssh/git_rich_lineups
```

Clone the repository, run the collector once by hand, then install the timer:

```bash
git clone https://github.com/LasseRogers/git-rich.git && cd git-rich
python3 pi/fetch_lineups.py --server ubuntu@<server> --key ~/.ssh/git_rich_lineups
pi/install-lineups-timer.sh ubuntu@<server>
```

`journalctl --user -u git-rich-lineups` shows each run.
