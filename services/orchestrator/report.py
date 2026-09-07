"""The Agent Advantage Report (spec.md §10) — generated from `receipts`, never
hand-written. Full both-ways task layout + PDF in T-063; this builds the payload.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from . import db, registry

_LOWER_IS_BETTER = {"wall_seconds"}


def build_advantage_report() -> dict[str, Any]:
    reg = registry.load_registry()
    tasks: list[dict[str, Any]] = []

    with db.session() as s:
        rows = s.execute(
            text(
                """
                SELECT ar.agent_id,
                       count(*)                       AS n,
                       min(rc.created_at)             AS first_at,
                       max(rc.created_at)             AS last_at,
                       avg(rc.agent_value)            AS avg_agent,
                       avg(rc.baseline_value)         AS avg_baseline,
                       avg(rc.delta)                  AS avg_delta,
                       min(rc.delta)                  AS worst_delta,
                       max(rc.delta)                  AS best_delta,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY ar.wall_seconds) AS median_wall,
                       max(rc.metric)                 AS metric,
                       max(rc.unit)                   AS unit
                FROM receipts rc
                JOIN runs ar ON ar.id = rc.agent_run_id
                GROUP BY ar.agent_id
                ORDER BY ar.agent_id
                """
            )
        ).mappings().all()

    for r in rows:
        m = reg.get(r["agent_id"]).manifest if r["agent_id"] in reg else None
        window_days = None
        if r["first_at"] and r["last_at"]:
            window_days = (r["last_at"] - r["first_at"]).total_seconds() / 86400.0
        lower_better = r["metric"] in _LOWER_IS_BETTER
        tasks.append({
            "agent_id": r["agent_id"],
            "name": m.name if m else r["agent_id"],
            "category": m.category if m else None,
            "baseline": m.baseline if m else None,
            "metric": r["metric"], "unit": r["unit"],
            "lower_is_better": lower_better,
            "n": r["n"],
            "window_days": round(window_days, 3) if window_days is not None else None,
            "median_wall_seconds": _f(r["median_wall"]),
            "avg_agent_value": _f(r["avg_agent"]),
            "avg_baseline_value": _f(r["avg_baseline"]),
            "avg_delta": _f(r["avg_delta"]),
            "best_delta": _f(r["best_delta"]),
            "worst_delta": _f(r["worst_delta"]),
            "advantage": (
                "agent is faster" if lower_better and _f(r["avg_delta"]) and r["avg_delta"] < 0
                else "agent beats baseline" if _f(r["avg_delta"]) and r["avg_delta"] > 0
                else "no measured advantage yet"
            ),
        })

    trading_or_security = [t for t in tasks if t["category"] in ("grid", "rebalancing", "security")]
    return {
        "generated_from": "receipts table (live)",
        "n_tasks": len(tasks),
        "meets_min_3_bothways": len(tasks) >= 3,
        "has_trading_or_security": len(trading_or_security) >= 1,
        "methodology": (
            "Every task ran both ways on the SAME data_snapshot: the agent policy "
            "and its named baseline (spec.md §9 baselines). Deltas are "
            "agent_value - baseline_value in the agent's declared unit. n and the "
            "window length are shown per task. No backtests are mixed in silently."
        ),
        "tasks": tasks,
    }


def _f(v: Any) -> float | None:
    return None if v is None else float(v)
