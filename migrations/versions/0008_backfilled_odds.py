"""backfilled odds

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Prices fetched after the fact, for backtests. Paper trading only acts on prices it saw live.
    op.execute("ALTER TABLE core.odds_snapshots ADD COLUMN backfilled boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE core.odds_snapshots DROP COLUMN backfilled")
