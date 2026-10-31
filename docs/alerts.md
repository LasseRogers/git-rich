# Phone alerts

git-rich sends alerts through [ntfy.sh](https://ntfy.sh), a free push service that needs no account. Install the ntfy app on your phone and subscribe to a topic; the server publishes to the same topic.

The topic name is the only secret: anyone who knows it can read and send its alerts. Generate a long random one instead of picking a name:

```bash
echo "git-rich-$(openssl rand -hex 12)"
```

Subscribe to it in the app, then set it in `.env`:

```bash
NTFY_TOPIC=git-rich-...
```

Leaving `NTFY_TOPIC` empty turns every alert off. Each kind also has its own switch, on unless set to `false`:

| Setting | Sent when |
|---|---|
| `ALERT_FAILURES` | a step of `scripts/update.sh` fails |
| `ALERT_UNMAPPED_TEAMS` | an upcoming match has a team that isn't in `team_aliases.csv`, so it can't be bet on |
| `ALERT_WORSE_MODEL` | a retrained model predicts the champion's test matches worse and is kept out |
| `ALERT_NEW_BETS` | a paper bet is placed, with the team, odds, bookmaker and start time |

The containers read the settings at start, so restart them after a change with `docker compose up -d`. To check the topic without waiting for an alert:

```bash
curl -d "Test from git-rich" "https://ntfy.sh/$(sed -n 's/^NTFY_TOPIC=//p' .env)"
```
