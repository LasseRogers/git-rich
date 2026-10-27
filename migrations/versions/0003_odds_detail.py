"""odds detail

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE core.odds_events ADD COLUMN tournament text")
    op.execute("ALTER TABLE core.odds_events ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()")

    # changed_at is the bookmaker's own price timestamp; captured_at is when we saw it.
    op.execute("ALTER TABLE core.odds_snapshots ADD COLUMN changed_at timestamptz")
    op.execute("ALTER TABLE core.odds_snapshots ADD COLUMN active boolean NOT NULL DEFAULT true")
    op.execute("CREATE INDEX ON core.odds_snapshots (odds_event_id, market, captured_at)")


def downgrade() -> None:
    op.execute("DROP INDEX core.odds_snapshots_odds_event_id_market_captured_at_idx")
    op.execute("ALTER TABLE core.odds_snapshots DROP COLUMN active")
    op.execute("ALTER TABLE core.odds_snapshots DROP COLUMN changed_at")
    op.execute("ALTER TABLE core.odds_events DROP COLUMN updated_at")
    op.execute("ALTER TABLE core.odds_events DROP COLUMN tournament")
