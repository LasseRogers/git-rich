"""automatic paper bets

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE core.bets ADD COLUMN p_market double precision CHECK (p_market BETWEEN 0 AND 1)")
    # Paper bets are placed by the strategy on every odds load; one per match keeps reruns idempotent.
    op.execute("CREATE UNIQUE INDEX bets_paper_event_key ON core.bets (odds_event_id) WHERE mode = 'paper'")


def downgrade() -> None:
    op.execute("DROP INDEX core.bets_paper_event_key")
    op.execute("ALTER TABLE core.bets DROP COLUMN p_market")
