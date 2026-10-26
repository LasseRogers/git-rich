from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from gitrich.config import database_url

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)


def run_offline() -> None:
    context.configure(url=database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
