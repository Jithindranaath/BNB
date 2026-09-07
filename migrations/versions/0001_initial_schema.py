"""initial schema (architecture.md §7)

Revision ID: 0001
Revises:
Create Date: 2026-09-07

Hand-written to match architecture.md §7 exactly. Two forced deviations, both
because `runs` is a TimescaleDB hypertable *when the extension is present*
(T-070: the hypertable + CREATE EXTENSION are guarded so this also applies to a
plain managed Postgres — the table shape and every query are unchanged):
  * runs PK is (id, started_at) — the partition column must be in every unique
    index; started_at is therefore NOT NULL DEFAULT now().
  * receipts has no DB-level FK to runs (a hypertable can't be an FK target
    cleanly). The harness writes both runs + the receipt in one transaction.
agent_stats is a plain table per §7's DDL; `refresh_agent_stats()` recomputes it
and a 60s job calls it (spec.md §7 "materialised view, refreshed every 60s").
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # TimescaleDB is used when present (local docker image), but the schema must
    # also apply to a plain managed Postgres (Neon / Render / Supabase free tier,
    # T-070) where the extension is unavailable. The composite PK (id, started_at)
    # and every query work identically on a non-partitioned `runs`.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
                CREATE EXTENSION IF NOT EXISTS timescaledb;
            END IF;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE agents (
            id         TEXT PRIMARY KEY,
            category   TEXT NOT NULL,
            manifest   JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE runs (
            id                 UUID NOT NULL DEFAULT gen_random_uuid(),
            agent_id           TEXT NOT NULL REFERENCES agents(id),
            kind               TEXT NOT NULL CHECK (kind IN ('agent','baseline')),
            pair_run_id        UUID,
            tier               SMALLINT NOT NULL,
            task_hash          TEXT NOT NULL,
            status             TEXT NOT NULL
                                 CHECK (status IN ('queued','running','ok','failed','halted')),
            started_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            ended_at           TIMESTAMPTZ,
            wall_seconds       NUMERIC,
            gas_wei            NUMERIC NOT NULL DEFAULT 0,
            protocol_fees_usd  NUMERIC NOT NULL DEFAULT 0,
            agent_fee_usd      NUMERIC NOT NULL DEFAULT 0,
            inputs             JSONB NOT NULL,
            outputs            JSONB,
            output_uri         TEXT,
            data_snapshot_hash TEXT NOT NULL,
            error              TEXT,
            PRIMARY KEY (id, started_at)
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                PERFORM create_hypertable('runs', by_range('started_at'));
            END IF;
        END $$
        """
    )
    op.execute("CREATE INDEX runs_agent_id_idx ON runs (agent_id, started_at DESC)")
    op.execute("CREATE INDEX runs_pair_run_id_idx ON runs (pair_run_id)")

    op.execute(
        """
        CREATE TABLE receipts (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_run_id    UUID NOT NULL,
            baseline_run_id UUID NOT NULL,
            metric          TEXT NOT NULL,
            unit            TEXT NOT NULL,
            agent_value     NUMERIC NOT NULL,
            baseline_value  NUMERIC NOT NULL,
            delta           NUMERIC NOT NULL,
            merkle_leaf     TEXT NOT NULL,
            batch_id        UUID,
            anchored_tx     TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX receipts_agent_run_id_idx ON receipts (agent_run_id)")
    op.execute("CREATE INDEX receipts_batch_id_idx ON receipts (batch_id)")

    op.execute(
        """
        CREATE TABLE agent_stats (
            agent_id            TEXT PRIMARY KEY REFERENCES agents(id),
            n_runs              INT NOT NULL DEFAULT 0,
            window_days         NUMERIC,
            median_wall_seconds NUMERIC,
            win_rate            NUMERIC,
            median_delta        NUMERIC,
            worst_delta         NUMERIC,
            max_drawdown_pct    NUMERIC,
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # Recompute agent_stats from runs + receipts. Called every 60s by the
    # orchestrator (T-060). max_drawdown_pct is filled by the trading agents' own
    # harness (T-040) and left untouched here.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION refresh_agent_stats() RETURNS void
        LANGUAGE sql AS $$
        INSERT INTO agent_stats AS s
            (agent_id, n_runs, window_days, median_wall_seconds, win_rate,
             median_delta, worst_delta, updated_at)
        SELECT
            a.id,
            count(ar.id),
            EXTRACT(EPOCH FROM (max(ar.started_at) - min(ar.started_at))) / 86400.0,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY ar.wall_seconds),
            avg((rc.delta > 0)::int)::numeric,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY rc.delta),
            min(rc.delta),
            now()
        FROM agents a
        LEFT JOIN runs ar     ON ar.agent_id = a.id AND ar.kind = 'agent' AND ar.status = 'ok'
        LEFT JOIN receipts rc ON rc.agent_run_id = ar.id
        GROUP BY a.id
        ON CONFLICT (agent_id) DO UPDATE SET
            n_runs              = EXCLUDED.n_runs,
            window_days         = EXCLUDED.window_days,
            median_wall_seconds = EXCLUDED.median_wall_seconds,
            win_rate            = EXCLUDED.win_rate,
            median_delta        = EXCLUDED.median_delta,
            worst_delta         = EXCLUDED.worst_delta,
            updated_at          = EXCLUDED.updated_at;
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS refresh_agent_stats()")
    op.execute("DROP TABLE IF EXISTS agent_stats")
    op.execute("DROP TABLE IF EXISTS receipts")
    op.execute("DROP TABLE IF EXISTS runs")
    op.execute("DROP TABLE IF EXISTS agents")
