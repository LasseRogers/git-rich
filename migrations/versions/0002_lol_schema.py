"""lol schema

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA lol")

    # Full source rows, so new features can be built without re-downloading.
    op.execute("""
        CREATE TABLE lol.raw_oracles_elixir (
            game_id         text NOT NULL,
            participant_id  smallint NOT NULL,
            data            jsonb NOT NULL,
            loaded_at       timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (game_id, participant_id)
        )
    """)

    op.execute("""
        CREATE TABLE lol.games (
            game_id            text PRIMARY KEY,
            match_id           bigint REFERENCES core.matches (id),
            league             text NOT NULL,
            year               smallint NOT NULL,
            split              text,
            playoffs           boolean NOT NULL,
            played_at          timestamptz NOT NULL,
            game_number        smallint,
            patch              text,
            blue_team_id       bigint NOT NULL REFERENCES core.teams (id),
            red_team_id        bigint NOT NULL REFERENCES core.teams (id),
            winner_side        text NOT NULL CHECK (winner_side IN ('blue', 'red')),
            duration_s         integer,
            data_completeness  text
        )
    """)
    op.execute("CREATE INDEX ON lol.games (match_id)")
    op.execute("CREATE INDEX ON lol.games (played_at)")

    op.execute("""
        CREATE TABLE lol.team_stats (
            game_id       text NOT NULL REFERENCES lol.games (game_id),
            side          text NOT NULL CHECK (side IN ('blue', 'red')),
            team_id       bigint NOT NULL REFERENCES core.teams (id),
            won           boolean NOT NULL,
            kills         smallint,
            deaths        smallint,
            assists       smallint,
            towers        smallint,
            inhibitors    smallint,
            dragons       smallint,
            barons        smallint,
            heralds       smallint,
            first_blood   boolean,
            first_dragon  boolean,
            first_herald  boolean,
            first_baron   boolean,
            first_tower   boolean,
            gold_diff_10  integer,
            gold_diff_15  integer,
            xp_diff_10    integer,
            xp_diff_15    integer,
            cs_diff_10    integer,
            cs_diff_15    integer,
            bans          text[],
            PRIMARY KEY (game_id, side)
        )
    """)
    op.execute("CREATE INDEX ON lol.team_stats (team_id)")

    op.execute("""
        CREATE TABLE lol.player_stats (
            game_id         text NOT NULL REFERENCES lol.games (game_id),
            side            text NOT NULL CHECK (side IN ('blue', 'red')),
            position        text NOT NULL CHECK (position IN ('top', 'jng', 'mid', 'bot', 'sup')),
            player_id       bigint NOT NULL REFERENCES core.players (id),
            team_id         bigint NOT NULL REFERENCES core.teams (id),
            champion        text NOT NULL,
            kills           smallint,
            deaths          smallint,
            assists         smallint,
            damage_per_min  real,
            damage_share    real,
            vision_per_min  real,
            earned_gpm      real,
            cs_per_min      real,
            gold_diff_10    integer,
            gold_diff_15    integer,
            xp_diff_10      integer,
            xp_diff_15      integer,
            cs_diff_10      integer,
            cs_diff_15      integer,
            PRIMARY KEY (game_id, side, position)
        )
    """)
    op.execute("CREATE INDEX ON lol.player_stats (player_id)")


def downgrade() -> None:
    op.execute("DROP SCHEMA lol CASCADE")
