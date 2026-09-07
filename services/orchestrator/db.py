"""SQLAlchemy 2.0 models for the schema in architecture.md §7.

Tables: agents, runs (TimescaleDB hypertable on started_at), receipts, agent_stats.
The DDL of record is the Alembic migration (migrations/versions/0001_*.py); these
models mirror it for ORM use by the harness (T-022).

Note: `runs` is a hypertable, so its PK includes the partition column
(id, started_at), and `receipts` does NOT carry a DB-level FK to `runs`
(TimescaleDB can't be the FK target cleanly) — the harness writes agent run,
baseline run and receipt in one transaction, so integrity holds in app code.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    Text,
    create_engine,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .config import config

RUN_KINDS = ("agent", "baseline")
RUN_STATUSES = ("queued", "running", "ok", "failed", "halted")


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(f"kind IN {RUN_KINDS!r}", name="runs_kind_chk"),
        CheckConstraint(f"status IN {RUN_STATUSES!r}", name="runs_status_chk"),
        Index("runs_agent_id_idx", "agent_id", "started_at"),
        Index("runs_pair_run_id_idx", "pair_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()"), primary_key=True
    )
    started_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), primary_key=True, nullable=False
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    pair_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    task_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    ended_at: Mapped[datetime | None]
    wall_seconds: Mapped[float | None] = mapped_column(Numeric)
    gas_wei: Mapped[float] = mapped_column(Numeric, server_default=text("0"), nullable=False)
    protocol_fees_usd: Mapped[float] = mapped_column(Numeric, server_default=text("0"), nullable=False)
    agent_fee_usd: Mapped[float] = mapped_column(Numeric, server_default=text("0"), nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    outputs: Mapped[dict | None] = mapped_column(JSONB)
    output_uri: Mapped[str | None] = mapped_column(Text)
    data_snapshot_hash: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (
        Index("receipts_agent_run_id_idx", "agent_run_id"),
        Index("receipts_batch_id_idx", "batch_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), server_default=text("gen_random_uuid()"), primary_key=True
    )
    agent_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    baseline_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    agent_value: Mapped[float] = mapped_column(Numeric, nullable=False)
    baseline_value: Mapped[float] = mapped_column(Numeric, nullable=False)
    delta: Mapped[float] = mapped_column(Numeric, nullable=False)
    merkle_leaf: Mapped[str] = mapped_column(Text, nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    anchored_tx: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class AgentStats(Base):
    __tablename__ = "agent_stats"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), primary_key=True)
    n_runs: Mapped[int] = mapped_column(server_default=text("0"), nullable=False)
    window_days: Mapped[float | None] = mapped_column(Numeric)
    median_wall_seconds: Mapped[float | None] = mapped_column(Numeric)
    win_rate: Mapped[float | None] = mapped_column(Numeric)
    median_delta: Mapped[float | None] = mapped_column(Numeric)
    worst_delta: Mapped[float | None] = mapped_column(Numeric)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Numeric)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            config().database_url,
            pool_pre_ping=True,
            future=True,
            connect_args={"connect_timeout": 10},
        )
    return _engine


def session() -> Session:
    return Session(engine(), future=True)
