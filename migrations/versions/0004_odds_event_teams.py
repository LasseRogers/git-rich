"""odds event teams

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE core.odds_events
            ADD COLUMN home_participant_id text,
            ADD COLUMN away_participant_id text,
            ADD COLUMN home_team_id bigint REFERENCES core.teams (id),
            ADD COLUMN away_team_id bigint REFERENCES core.teams (id)
    """)
    op.execute("CREATE INDEX ON core.matches (team1_id, team2_id, start_time)")


def downgrade() -> None:
    op.execute("DROP INDEX core.matches_team1_id_team2_id_start_time_idx")
    op.execute("""
        ALTER TABLE core.odds_events
            DROP COLUMN away_team_id,
            DROP COLUMN home_team_id,
            DROP COLUMN away_participant_id,
            DROP COLUMN home_participant_id
    """)
