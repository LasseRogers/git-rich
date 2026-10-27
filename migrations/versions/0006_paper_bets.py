"""paper bets on upcoming matches

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Bets are placed before the result exists, so they hang off the odds event and gain a match on settlement.
    op.execute("""
        ALTER TABLE core.bets
            ALTER COLUMN match_id DROP NOT NULL,
            ADD COLUMN odds_event_id bigint REFERENCES core.odds_events (id),
            ADD COLUMN market text NOT NULL DEFAULT 'winner',
            ADD COLUMN selection text CHECK (selection IN ('team1', 'team2')),
            ADD COLUMN p_model double precision CHECK (p_model BETWEEN 0 AND 1),
            ADD COLUMN clv double precision,
            ADD COLUMN settled_at timestamptz,
            ADD CONSTRAINT bets_target CHECK (match_id IS NOT NULL OR odds_event_id IS NOT NULL)
    """)
    op.execute("CREATE INDEX ON core.bets (odds_event_id)")
    op.execute("CREATE INDEX ON core.bets (result)")


def downgrade() -> None:
    op.execute("DROP INDEX core.bets_result_idx")
    op.execute("DROP INDEX core.bets_odds_event_id_idx")
    op.execute("""
        ALTER TABLE core.bets
            DROP CONSTRAINT bets_target,
            DROP COLUMN settled_at,
            DROP COLUMN clv,
            DROP COLUMN p_model,
            DROP COLUMN selection,
            DROP COLUMN market,
            DROP COLUMN odds_event_id
    """)
    op.execute("DELETE FROM core.bets WHERE match_id IS NULL")
    op.execute("ALTER TABLE core.bets ALTER COLUMN match_id SET NOT NULL")
