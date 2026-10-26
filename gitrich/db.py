import psycopg

from gitrich.config import database_url


def connect() -> psycopg.Connection:
    # DATABASE_URL carries the SQLAlchemy driver prefix for Alembic; psycopg wants the plain form.
    return psycopg.connect(database_url().replace("postgresql+psycopg://", "postgresql://", 1))
