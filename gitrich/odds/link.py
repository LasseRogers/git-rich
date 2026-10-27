import csv
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)

SOURCE = "oddspapi"
ALIASES = Path(os.environ.get("TEAM_ALIASES", Path(__file__).with_name("team_aliases.csv")))

# Words that one source includes and the other drops, e.g. "Bilibili Gaming" vs "Bilibili".
FILLER = {"esports", "esport", "gaming", "team", "club", "the"}

# A team counts as current if it played within this window; avoids matching long-disbanded namesakes.
ACTIVE_DAYS = 400

# Oracle's Elixir dates the first game, which starts at or after the scheduled time.
MATCH_WINDOW = ("3 hours", "12 hours")


@dataclass
class LinkStats:
    teams: int
    matches: int
    unmapped: list[str] = field(default_factory=list)


# Letters NFKD doesn't decompose into ASCII, so they would otherwise be dropped ("LØS" -> "ls").
TRANSLITERATE = str.maketrans({
    "ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ß": "ss",
    "đ": "d", "Đ": "D", "ð": "d", "Ð": "D", "ł": "l", "Ł": "L", "þ": "th", "Þ": "TH",
})


def normalize(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name.translate(TRANSLITERATE))
    ascii_name = ascii_name.encode("ascii", "ignore").decode().lower()
    words = re.sub(r"[^a-z0-9]+", " ", ascii_name).split()
    return "".join(w for w in words if w not in FILLER)


def link(conn: psycopg.Connection) -> LinkStats:
    teams = _map_teams(conn)
    matches = _link_matches(conn)
    unmapped = [
        name for (name,) in conn.execute("""
            SELECT DISTINCT name FROM (
                SELECT home_name AS name FROM core.odds_events WHERE home_team_id IS NULL
                UNION
                SELECT away_name FROM core.odds_events WHERE away_team_id IS NULL
            ) n ORDER BY name
        """)
    ]
    return LinkStats(teams=teams, matches=matches, unmapped=unmapped)


def _map_teams(conn: psycopg.Connection) -> int:
    candidates: dict[str, int] = {}
    by_name: dict[str, int] = {}
    # Ordered oldest first, so when names collide the most recently active team wins.
    for team_id, name in conn.execute(
        f"""
        SELECT t.id, t.name
        FROM core.teams t
        JOIN lol.team_stats s ON s.team_id = t.id
        JOIN lol.games g ON g.game_id = s.game_id
        WHERE t.title = 'lol' AND g.played_at > now() - interval '{ACTIVE_DAYS} days'
        GROUP BY t.id, t.name
        ORDER BY max(g.played_at)
        """
    ):
        candidates[normalize(name)] = team_id
        by_name[name] = team_id

    aliases = _aliases()
    mapped = 0

    # Aliases win over earlier automatic matches, so a wrong match is fixed by adding an alias.
    for participant_id, name in conn.execute(
        """
        SELECT DISTINCT p.participant_id, p.name
        FROM core.odds_events e
        CROSS JOIN LATERAL (VALUES (e.home_participant_id, e.home_name),
                                   (e.away_participant_id, e.away_name)) p (participant_id, name)
        WHERE p.name = ANY(%s)
        """,
        (list(aliases),),
    ).fetchall():
        team_id = by_name.get(aliases[name])
        if team_id is None:
            log.warning("alias %r -> %r: no active team with that name", name, aliases[name])
            continue
        cur = conn.execute(
            """
            INSERT INTO core.team_sources (team_id, source, external_id) VALUES (%s, %s, %s)
            ON CONFLICT (source, external_id) DO UPDATE SET team_id = EXCLUDED.team_id
            WHERE core.team_sources.team_id <> EXCLUDED.team_id
            """,
            (team_id, SOURCE, participant_id),
        )
        mapped += cur.rowcount

    unmapped = conn.execute(
        """
        SELECT DISTINCT p.participant_id, p.name
        FROM core.odds_events e
        CROSS JOIN LATERAL (VALUES (e.home_participant_id, e.home_name),
                                   (e.away_participant_id, e.away_name)) p (participant_id, name)
        LEFT JOIN core.team_sources s ON s.source = %s AND s.external_id = p.participant_id
        WHERE p.participant_id IS NOT NULL AND s.team_id IS NULL
        """,
        (SOURCE,),
    ).fetchall()

    for participant_id, name in unmapped:
        team_id = candidates.get(normalize(name))
        if team_id is None:
            continue
        conn.execute(
            "INSERT INTO core.team_sources (team_id, source, external_id) VALUES (%s, %s, %s)",
            (team_id, SOURCE, participant_id),
        )
        mapped += 1

    conn.execute(
        """
        UPDATE core.odds_events e SET
            home_team_id = (SELECT team_id FROM core.team_sources
                            WHERE source = %(s)s AND external_id = e.home_participant_id),
            away_team_id = (SELECT team_id FROM core.team_sources
                            WHERE source = %(s)s AND external_id = e.away_participant_id)
        WHERE e.source = %(s)s
        """,
        {"s": SOURCE},
    )
    return mapped


def _link_matches(conn: psycopg.Connection) -> int:
    # Team mappings can change through aliases; drop links that no longer agree with the teams.
    conn.execute("""
        UPDATE core.odds_events e SET match_id = NULL
        FROM core.matches m
        WHERE m.id = e.match_id
          AND (least(m.team1_id, m.team2_id), greatest(m.team1_id, m.team2_id))
              IS DISTINCT FROM (least(e.home_team_id, e.away_team_id), greatest(e.home_team_id, e.away_team_id))
    """)
    cur = conn.execute(
        f"""
        WITH candidates AS (
            SELECT e.id, (
                SELECT m.id FROM core.matches m
                WHERE least(m.team1_id, m.team2_id) = least(e.home_team_id, e.away_team_id)
                  AND greatest(m.team1_id, m.team2_id) = greatest(e.home_team_id, e.away_team_id)
                  AND m.start_time BETWEEN e.start_time - interval '{MATCH_WINDOW[0]}'
                                       AND e.start_time + interval '{MATCH_WINDOW[1]}'
                ORDER BY abs(extract(epoch FROM m.start_time - e.start_time))
                LIMIT 1
            ) AS match_id
            FROM core.odds_events e
            WHERE e.match_id IS NULL AND e.home_team_id IS NOT NULL AND e.away_team_id IS NOT NULL
        )
        UPDATE core.odds_events e SET match_id = c.match_id
        FROM candidates c
        WHERE e.id = c.id AND c.match_id IS NOT NULL
        """
    )
    return cur.rowcount


def _aliases() -> dict[str, str]:
    with ALIASES.open(newline="") as f:
        return {row["oddspapi_name"]: row["team_name"] for row in csv.DictReader(f)}
