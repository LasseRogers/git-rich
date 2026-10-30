"""source files

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The version of each Oracle's Elixir file that was loaded, so updates only reload files that changed.
    op.execute("""
        CREATE TABLE lol.source_files (
            name         text PRIMARY KEY,
            modified_at  timestamptz NOT NULL,
            loaded_at    timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE lol.source_files")
