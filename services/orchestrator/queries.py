"""DB read helpers for the API. All reads go through here so the routes stay thin."""

from __future__ import annotations

from typing import Any

from agents.manifest import Manifest
from sqlalchemy import text

from . import db, registry
from .schemas import (
    AgentCard,
    AgentDetail,
    AgentStatsOut,
    CategoryOut,
    Curve,
    ReceiptOut,
)


def refresh_stats() -> None:
    with db.session() as s:
        s.execute(text("SELECT refresh_agent_stats()"))
        s.commit()


def sync_registry_to_db() -> list[str]:
    """Upsert every valid manifest into `agents` so the marketplace lists them
    before any hire has run."""
    synced = []
    for entry in registry.load_registry().values():
        if not entry.available or entry.manifest is None:
            continue
        _upsert_agent(entry.manifest)
        synced.append(entry.id)
    return synced


def _upsert_agent(m: Manifest) -> None:
    with db.session() as s:
        s.execute(
            text(
                """
                INSERT INTO agents (id, category, manifest)
                VALUES (:id, :category, CAST(:manifest AS jsonb))
                ON CONFLICT (id) DO UPDATE SET category = EXCLUDED.category,
                                               manifest = EXCLUDED.manifest
                """
            ),
            {"id": m.id, "category": m.category, "manifest": m.model_dump_json()},
        )
        s.commit()


def _stats_row(agent_id: str) -> AgentStatsOut:
    with db.session() as s:
        row = s.execute(
            text("SELECT * FROM agent_stats WHERE agent_id = :id"), {"id": agent_id}
        ).mappings().first()
    if not row:
        return AgentStatsOut()
    return AgentStatsOut(
        n_runs=row["n_runs"] or 0,
        window_days=_f(row["window_days"]),
        median_wall_seconds=_f(row["median_wall_seconds"]),
        win_rate=_f(row["win_rate"]),
        median_delta=_f(row["median_delta"]),
        worst_delta=_f(row["worst_delta"]),
        max_drawdown_pct=_f(row["max_drawdown_pct"]),
        updated_at=row["updated_at"],
    )


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _card(m: Manifest) -> AgentCard:
    st = _stats_row(m.id)
    return AgentCard(
        id=m.id, name=m.name, category=m.category, one_liner=m.one_liner,
        tiers=list(m.tiers), pricing=m.pricing, advantage_metric=m.advantage_metric,
        sentry_gate=m.sentry_gate, stats=st, has_runs=st.n_runs > 0,
    )


def agent_cards() -> list[AgentCard]:
    refresh_stats()
    return [_card(e.manifest) for e in registry.load_registry().values()
            if e.available and e.manifest]


def agent_detail(agent_id: str) -> AgentDetail | None:
    e = registry.load_registry().get(agent_id)
    if not e or not e.available or e.manifest is None:
        return None
    refresh_stats()
    m = e.manifest
    receipts = receipts_for(agent_id, limit=25)
    pts = [
        {"created_at": r.created_at.isoformat(), "agent_value": r.agent_value,
         "baseline_value": r.baseline_value, "delta": r.delta}
        for r in reversed(receipts)
    ]
    st = _stats_row(agent_id)
    curve = Curve(metric=m.advantage_metric.name, unit=m.advantage_metric.unit,
                  window_days=st.window_days, points=pts)
    base = _card(m).model_dump()
    return AgentDetail(
        **base,
        inputs=m.inputs, data_deps=list(m.data_deps), baseline=m.baseline,
        kill_switch=(m.kill_switch.model_dump() if m.kill_switch else None),
        recent_receipts=receipts, curve=curve,
    )


def receipts_for(agent_id: str, *, limit: int = 25) -> list[ReceiptOut]:
    with db.session() as s:
        rows = s.execute(
            text(
                """
                SELECT r.*, ar.agent_id AS agent_id
                FROM receipts r
                JOIN runs ar ON ar.id = r.agent_run_id
                WHERE ar.agent_id = :id
                ORDER BY r.created_at DESC
                LIMIT :lim
                """
            ),
            {"id": agent_id, "lim": limit},
        ).mappings().all()
    return [_receipt_out(row) for row in rows]


def receipt_by_id(receipt_id: str) -> ReceiptOut | None:
    with db.session() as s:
        row = s.execute(
            text(
                """
                SELECT r.*, ar.agent_id AS agent_id
                FROM receipts r JOIN runs ar ON ar.id = r.agent_run_id
                WHERE r.id = :id
                """
            ),
            {"id": receipt_id},
        ).mappings().first()
    return _receipt_out(row) if row else None


def _receipt_out(row) -> ReceiptOut:
    delta = float(row["delta"])
    return ReceiptOut(
        id=str(row["id"]), agent_id=row["agent_id"],
        agent_run_id=str(row["agent_run_id"]), baseline_run_id=str(row["baseline_run_id"]),
        metric=row["metric"], unit=row["unit"],
        agent_value=float(row["agent_value"]), baseline_value=float(row["baseline_value"]),
        delta=delta, favorable=_favorable(row["metric"], delta),
        merkle_leaf=row["merkle_leaf"],
        batch_id=str(row["batch_id"]) if row["batch_id"] else None,
        anchored_tx=row["anchored_tx"], created_at=row["created_at"],
    )


_LOWER_IS_BETTER = {"wall_seconds"}


def _favorable(metric: str, delta: float) -> bool:
    if delta == 0:
        return False
    return delta < 0 if metric in _LOWER_IS_BETTER else delta > 0


def recent_receipts(limit: int = 20) -> list[ReceiptOut]:
    with db.session() as s:
        rows = s.execute(
            text(
                """
                SELECT r.*, ar.agent_id AS agent_id
                FROM receipts r JOIN runs ar ON ar.id = r.agent_run_id
                ORDER BY r.created_at DESC LIMIT :lim
                """
            ),
            {"lim": limit},
        ).mappings().all()
    return [_receipt_out(row) for row in rows]


def categories() -> list[CategoryOut]:
    counts: dict[str, int] = {}
    for e in registry.load_registry().values():
        if e.available and e.manifest:
            counts[e.manifest.category] = counts.get(e.manifest.category, 0) + 1
    with db.session() as s:
        live = dict(s.execute(text(
            """
            SELECT a.category, count(*) FROM runs r
            JOIN agents a ON a.id = r.agent_id
            WHERE r.started_at > now() - interval '24 hours'
            GROUP BY a.category
            """
        )).all())
    return [CategoryOut(category=c, agent_count=n, live_runs=int(live.get(c, 0)))
            for c, n in sorted(counts.items())]
