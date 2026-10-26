"""core schema

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA core")

    op.execute("""
        CREATE TABLE core.teams (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            title       text NOT NULL,
            name        text NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE core.team_sources (
            team_id      bigint NOT NULL REFERENCES core.teams (id),
            source       text NOT NULL,
            external_id  text NOT NULL,
            PRIMARY KEY (source, external_id)
        )
    """)

    op.execute("""
        CREATE TABLE core.players (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            title       text NOT NULL,
            handle      text NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE core.player_sources (
            player_id    bigint NOT NULL REFERENCES core.players (id),
            source       text NOT NULL,
            external_id  text NOT NULL,
            PRIMARY KEY (source, external_id)
        )
    """)

    op.execute("""
        CREATE TABLE core.matches (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            title        text NOT NULL,
            source       text NOT NULL,
            external_id  text NOT NULL,
            league       text NOT NULL,
            start_time   timestamptz NOT NULL,
            best_of      smallint,
            team1_id     bigint NOT NULL REFERENCES core.teams (id),
            team2_id     bigint NOT NULL REFERENCES core.teams (id),
            team1_score  smallint,
            team2_score  smallint,
            winner_id    bigint REFERENCES core.teams (id),
            status       text NOT NULL DEFAULT 'scheduled'
                         CHECK (status IN ('scheduled', 'live', 'finished', 'cancelled')),
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source, external_id),
            CHECK (team1_id <> team2_id)
        )
    """)
    op.execute("CREATE INDEX ON core.matches (title, start_time)")

    op.execute("""
        CREATE TABLE core.odds_events (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source       text NOT NULL,
            external_id  text NOT NULL,
            title        text NOT NULL,
            home_name    text NOT NULL,
            away_name    text NOT NULL,
            start_time   timestamptz NOT NULL,
            match_id     bigint REFERENCES core.matches (id),
            UNIQUE (source, external_id)
        )
    """)
    op.execute("CREATE INDEX ON core.odds_events (match_id)")

    op.execute("""
        CREATE TABLE core.odds_snapshots (
            id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            odds_event_id  bigint NOT NULL REFERENCES core.odds_events (id),
            bookmaker      text NOT NULL,
            market         text NOT NULL,
            selection      text NOT NULL,
            price          numeric(8, 3) NOT NULL CHECK (price > 1),
            captured_at    timestamptz NOT NULL,
            UNIQUE (odds_event_id, bookmaker, market, selection, captured_at)
        )
    """)

    op.execute("""
        CREATE TABLE core.predictions (
            id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            match_id       bigint NOT NULL REFERENCES core.matches (id),
            model_name     text NOT NULL,
            model_version  text NOT NULL,
            p_team1        double precision NOT NULL CHECK (p_team1 BETWEEN 0 AND 1),
            created_at     timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON core.predictions (match_id)")

    op.execute("""
        CREATE TABLE core.bets (
            id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            match_id       bigint NOT NULL REFERENCES core.matches (id),
            prediction_id  bigint REFERENCES core.predictions (id),
            team_id        bigint NOT NULL REFERENCES core.teams (id),
            bookmaker      text NOT NULL,
            price          numeric(8, 3) NOT NULL CHECK (price > 1),
            stake          numeric(12, 2) NOT NULL CHECK (stake > 0),
            mode           text NOT NULL DEFAULT 'paper' CHECK (mode IN ('paper', 'real')),
            placed_at      timestamptz NOT NULL DEFAULT now(),
            closing_price  numeric(8, 3),
            result         text NOT NULL DEFAULT 'pending'
                           CHECK (result IN ('pending', 'won', 'lost', 'void')),
            pnl            numeric(12, 2)
        )
    """)
    op.execute("CREATE INDEX ON core.bets (match_id)")


def downgrade() -> None:
    op.execute("DROP SCHEMA core CASCADE")
