"""a second paper strategy that bets against Pinnacle's line without the model

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE core.bets
            ADD COLUMN strategy text NOT NULL DEFAULT 'model' CHECK (strategy IN ('model', 'sharp'))
    """)
    # One paper bet per match and strategy, so the strategies are judged on the same matches independently.
    op.execute("DROP INDEX core.bets_paper_event_key")
    op.execute("CREATE UNIQUE INDEX bets_paper_event_key ON core.bets (odds_event_id, strategy) WHERE mode = 'paper'")


def downgrade() -> None:
    op.execute("DELETE FROM core.bets WHERE strategy <> 'model'")
    op.execute("DROP INDEX core.bets_paper_event_key")
    op.execute("CREATE UNIQUE INDEX bets_paper_event_key ON core.bets (odds_event_id) WHERE mode = 'paper'")
    op.execute("ALTER TABLE core.bets DROP COLUMN strategy")
