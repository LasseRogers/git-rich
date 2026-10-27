"""upcoming predictions

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Upcoming matches only exist as odds events until the result is ingested, so a prediction
    # can point at either, and names its own team order.
    op.execute("""
        ALTER TABLE core.predictions
            ALTER COLUMN match_id DROP NOT NULL,
            ADD COLUMN odds_event_id bigint REFERENCES core.odds_events (id),
            ADD COLUMN team1_id bigint REFERENCES core.teams (id),
            ADD COLUMN team2_id bigint REFERENCES core.teams (id),
            ADD COLUMN best_of smallint,
            ADD COLUMN features jsonb,
            ADD CONSTRAINT predictions_target CHECK (match_id IS NOT NULL OR odds_event_id IS NOT NULL)
    """)
    # The first pre-match prediction per model version is the one that counts for paper trading.
    op.execute("CREATE UNIQUE INDEX ON core.predictions (odds_event_id, model_name, model_version)")


def downgrade() -> None:
    op.execute("DROP INDEX core.predictions_odds_event_id_model_name_model_version_idx")
    op.execute("""
        ALTER TABLE core.predictions
            DROP CONSTRAINT predictions_target,
            DROP COLUMN features,
            DROP COLUMN best_of,
            DROP COLUMN team2_id,
            DROP COLUMN team1_id,
            DROP COLUMN odds_event_id
    """)
    op.execute("DELETE FROM core.predictions WHERE match_id IS NULL")
    op.execute("ALTER TABLE core.predictions ALTER COLUMN match_id SET NOT NULL")
