"""Alembic environment. URL comes from orchestrator.config unless the caller
set `sqlalchemy.url` explicitly (the migration test points it at a scratch DB)."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from orchestrator.config import config as orch_config
from orchestrator.db import Base
from sqlalchemy import engine_from_config, pool

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

if not alembic_config.get_main_option("sqlalchemy.url"):
    alembic_config.set_main_option("sqlalchemy.url", orch_config().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=alembic_config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10},
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
