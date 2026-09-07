"""T-021 acceptance: the Alembic migration builds architecture.md §7 cleanly and
`runs` is a TimescaleDB hypertable. Needs the docker postgres (timescaledb) up.

Runs downgrade->base then upgrade->head on the dev DB (fast: the timescaledb
extension is already installed), asserts the schema, and leaves it at head.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from orchestrator.config import config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.live

REPO = Path(__file__).resolve().parents[1]
OUR_TABLES = {"agents", "runs", "receipts", "agent_stats"}


@pytest.fixture
def alembic_cfg() -> Config:
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    cfg.set_main_option("sqlalchemy.url", config().database_url)
    return cfg


def _public_tables(conn) -> set[str]:
    rows = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    ).scalars()
    return set(rows)


def test_migration_clean_and_hypertable(alembic_cfg):
    eng = create_engine(config().database_url, future=True)

    command.downgrade(alembic_cfg, "base")
    with eng.connect() as c:
        assert OUR_TABLES.isdisjoint(_public_tables(c)), "downgrade left tables behind"

    command.upgrade(alembic_cfg, "head")

    with eng.connect() as c:
        assert OUR_TABLES <= _public_tables(c)

        hypertables = set(
            c.execute(
                text("SELECT hypertable_name FROM timescaledb_information.hypertables")
            ).scalars()
        )
        assert "runs" in hypertables

        # runs PK includes the partition column
        pk_cols = set(
            c.execute(
                text(
                    """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = 'runs'::regclass AND i.indisprimary
                    """
                )
            ).scalars()
        )
        assert pk_cols == {"id", "started_at"}

        # the 60s refresh function exists and runs on an empty schema
        c.execute(text("SELECT refresh_agent_stats()"))
        c.commit()

        # kind/status CHECK constraints are enforced
        c.execute(
            text(
                "INSERT INTO agents (id, category, manifest) VALUES ('x','security','{}'::jsonb)"
            )
        )
        with pytest.raises(IntegrityError):
            c.execute(
                text(
                    """
                    INSERT INTO runs (agent_id, kind, tier, task_hash, status,
                                      inputs, data_snapshot_hash)
                    VALUES ('x', 'not-a-kind', 0, 'h', 'ok', '{}'::jsonb, 'h')
                    """
                )
            )
        c.rollback()
