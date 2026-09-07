"""The Agent Advantage Report (spec.md §10) — generated from `receipts`, never
hand-written.

Per task we report, straight from the tables:
  - time     : median agent wall vs the baseline's wall (for bsc-sentry the
               baseline wall is a *human* stopwatch, so the contrast is real)
  - cost     : on-chain gas + protocol fees + agent fee actually recorded on the
               agent run; simulated runs carry $0 and say so
  - output   : delta distribution, win rate, and per-receipt links to /receipt/<id>
  - n, window length, methodology, and — for replayed strategies — a BACKTEST
    label with the replay method spelled out. Backtests are never folded
    silently into live numbers.

`GET /report/advantage` returns this payload; `GET /report/advantage.pdf` renders
it (build_advantage_pdf).
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from . import db, registry

# categories whose Tier 0/1 runs are historical replays, not live execution
_BACKTEST_CATEGORIES = {"grid", "rebalancing", "health_factor"}

_REPLAY_METHOD = {
    "grid": (
        "Policy re-simulated slot-by-slot over historical Binance BNBUSDT klines "
        "for the window above; the hodl baseline is marked to market on the same "
        "kline snapshot. No capital deployed."
    ),
    "rebalancing": (
        "PancakeSwap v3 position lifecycle replayed over historical klines for the "
        "window; the static-range baseline is evaluated on the same snapshot. Fee "
        "APR is pulled live from DefiLlama at run time. No capital deployed."
    ),
    "health_factor": (
        "Health factor recomputed along a historical price drawdown path; the "
        "no_action baseline replays the liquidation on that same path. No capital "
        "deployed."
    ),
}

# spec.md §10 planned tasks — used to render an explicit row even when a task has
# not produced a receipt yet (rule R2: explicit empty state, never a fake number).
_PLANNED = [
    {"agent_id": "bnb-grid", "task": "Grid on BNB/USDT, live window, small real capital",
     "baseline": "hodl", "headline": "net PnL, win rate, max drawdown, window"},
    {"agent_id": "bsc-sentry", "task": "Audit BSC tokens against a manual analyst",
     "baseline": "manual_analyst (human, stopwatch)", "headline": "wall time + findings diff"},
    {"agent_id": "pcs-rebalancer", "task": "PCS v3 LP, same pair / capital / window",
     "baseline": "static_range", "headline": "net fees after gas + IL"},
    {"agent_id": "pcs-yield", "task": "Yield routing across PCS v3 pools",
     "baseline": "top_headline_apr", "headline": "net APR delta"},
]

_NOT_RUN_REASON = {
    "bsc-sentry": (
        "No both-ways receipts yet: the baseline is a human analyst timed with a "
        "stopwatch (fixtures/manual_baselines.json) and no real audit has been "
        "recorded — only the sample row. Rule R2/R3: not fabricated to fill the "
        "table."
    ),
    "pcs-yield": (
        "Held (T-033): needs a working The Graph query key for the PancakeSwap v3 "
        "subgraph. Rule R1 forbids inventing pool data, so the agent stays parked "
        "until the key is live."
    ),
}


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _favorable(delta: float, higher_is_better: bool) -> bool:
    return delta > 0 if higher_is_better else delta < 0


def _eval_window_days(agent_outputs: Any) -> float | None:
    """The market window the strategy was actually evaluated over — pulled from
    the agent's own result, not the gap between receipt timestamps."""
    if not isinstance(agent_outputs, dict):
        return None
    inner = (agent_outputs.get("result") or {}).get("outputs") or {}
    stats = inner.get("stats") or {}
    if isinstance(stats.get("window_days"), (int, float)):
        return round(float(stats["window_days"]), 3)
    if isinstance(inner.get("stress_days"), (int, float)):
        return round(float(inner["stress_days"]), 3)
    return None


def _fetch_rows() -> list[dict[str, Any]]:
    with db.session() as s:
        return [
            dict(r) for r in s.execute(
                text(
                    """
                    SELECT rc.id            AS receipt_id,
                           rc.agent_run_id, rc.baseline_run_id,
                           rc.metric, rc.unit,
                           rc.agent_value, rc.baseline_value, rc.delta,
                           rc.created_at, rc.batch_id, rc.anchored_tx,
                           ar.agent_id,
                           ar.tier                 AS agent_tier,
                           ar.status               AS agent_status,
                           ar.wall_seconds         AS agent_wall,
                           ar.gas_wei              AS agent_gas_wei,
                           ar.protocol_fees_usd    AS agent_fees_usd,
                           ar.agent_fee_usd        AS agent_fee_usd,
                           ar.output_uri           AS agent_output_uri,
                           ar.outputs              AS agent_outputs,
                           ar.data_snapshot_hash   AS snapshot_hash,
                           br.wall_seconds         AS baseline_wall,
                           br.status               AS baseline_status
                    FROM receipts rc
                    JOIN runs ar ON ar.id = rc.agent_run_id
                    JOIN runs br ON br.id = rc.baseline_run_id
                    ORDER BY ar.agent_id, rc.created_at
                    """
                )
            ).mappings().all()
        ]


def _task_for_group(agent_id: str, rows: list[dict[str, Any]], reg: dict) -> dict[str, Any]:
    entry = reg.get(agent_id)
    m = entry.manifest if entry else None
    category = m.category if m else None
    higher_is_better = m.advantage_metric.higher_is_better if m else True

    deltas = [float(r["delta"]) for r in rows]
    agent_walls = [float(r["agent_wall"]) for r in rows if r["agent_wall"] is not None]
    base_walls = [float(r["baseline_wall"]) for r in rows if r["baseline_wall"] is not None]
    first_at = min(r["created_at"] for r in rows)
    last_at = max(r["created_at"] for r in rows)
    receipts_span_days = (last_at - first_at).total_seconds() / 86400.0
    newest = max(rows, key=lambda x: x["created_at"])
    eval_window_days = _eval_window_days(newest["agent_outputs"])

    wins = sum(1 for d in deltas if _favorable(d, higher_is_better))
    losses = sum(1 for d in deltas if _favorable(-d, higher_is_better))
    best = max(deltas) if higher_is_better else min(deltas)
    worst = min(deltas) if higher_is_better else max(deltas)

    gas_wei = sum(float(r["agent_gas_wei"] or 0) for r in rows)
    fees_usd = sum(float(r["agent_fees_usd"] or 0) for r in rows)
    agent_fee_usd = sum(float(r["agent_fee_usd"] or 0) for r in rows)
    on_chain = gas_wei > 0 or fees_usd > 0 or agent_fee_usd > 0

    max_tier = max(int(r["agent_tier"]) for r in rows)
    is_backtest = category in _BACKTEST_CATEGORIES and max_tier <= 1
    kind = "BACKTEST" if is_backtest else "LIVE"

    agent_median = statistics.median(agent_walls) if agent_walls else None
    base_median = statistics.median(base_walls) if base_walls else None

    return {
        "agent_id": agent_id,
        "name": m.name if m else agent_id,
        "category": category,
        "baseline": m.baseline if m else None,
        "metric": rows[0]["metric"],
        "unit": rows[0]["unit"],
        "higher_is_better": higher_is_better,
        "kind": kind,
        "replay_method": _REPLAY_METHOD.get(category) if is_backtest else None,
        "both_ways": True,
        "n": len(rows),
        "evaluation_window_days": eval_window_days,
        "receipts_span_days": round(receipts_span_days, 3),
        "window_note": (
            "evaluation_window_days = the market window the strategy was replayed "
            "over (from the agent's own result); receipts_span_days = wall-clock "
            "spread of the runs that produced these receipts"
        ),
        "first_at": first_at.isoformat(),
        "last_at": last_at.isoformat(),
        "distinct_snapshots": len({r["snapshot_hash"] for r in rows}),
        "time": {
            "agent_median_seconds": round(agent_median, 3) if agent_median is not None else None,
            "agent_p90_seconds": (
                round(sorted(agent_walls)[max(0, int(len(agent_walls) * 0.9) - 1)], 3)
                if agent_walls else None
            ),
            "baseline_median_seconds": round(base_median, 3) if base_median is not None else None,
            "baseline_is_human": m.baseline == "manual_analyst" if m else False,
            "speedup_x": (
                round(base_median / agent_median, 1)
                if agent_median and base_median and agent_median > 0 else None
            ),
        },
        "cost": {
            "on_chain": on_chain,
            "agent_gas_wei": gas_wei if on_chain else 0,
            "agent_gas_bnb": round(gas_wei / 1e18, 9) if on_chain else 0,
            "protocol_fees_usd": round(fees_usd, 4),
            "agent_fee_usd": round(agent_fee_usd, 4),
            "note": None if on_chain else "simulated run - no transaction sent, on-chain cost $0",
        },
        "output_quality": {
            "avg_delta": round(statistics.fmean(deltas), 6),
            "median_delta": round(statistics.median(deltas), 6),
            "best_delta": round(best, 6),
            "worst_delta": round(worst, 6),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(deltas), 3) if deltas else None,
            "verdict": (
                "agent beats baseline" if statistics.fmean(deltas) and
                _favorable(statistics.fmean(deltas), higher_is_better)
                else "no measured advantage"
            ),
        },
        "outputs": [
            {
                "receipt_id": str(r["receipt_id"]),
                "url": f"/receipt/{r['receipt_id']}",
                "delta": round(float(r["delta"]), 6),
                "favorable": _favorable(float(r["delta"]), higher_is_better),
                "created_at": r["created_at"].isoformat(),
                "output_uri": r["agent_output_uri"],
                "anchored": bool(r["anchored_tx"]),
                "batch_id": str(r["batch_id"]) if r["batch_id"] else None,
            }
            for r in sorted(rows, key=lambda x: x["created_at"], reverse=True)[:12]
        ],
    }


def build_advantage_report() -> dict[str, Any]:
    reg = registry.load_registry()
    rows = _fetch_rows()

    by_agent: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_agent.setdefault(r["agent_id"], []).append(r)

    tasks = [_task_for_group(aid, grp, reg) for aid, grp in sorted(by_agent.items())]
    have = {t["agent_id"] for t in tasks}

    planned = [
        {
            "agent_id": p["agent_id"],
            "task": p["task"],
            "baseline": p["baseline"],
            "headline_metric": p["headline"],
            "status": "has receipts" if p["agent_id"] in have else "not yet run",
            "reason": None if p["agent_id"] in have else _NOT_RUN_REASON.get(
                p["agent_id"], "no both-ways receipts recorded yet"
            ),
        }
        for p in _PLANNED
    ]

    trading_or_security = [t for t in tasks if t["category"] in ("grid", "rebalancing", "security")]
    backtests = [t["agent_id"] for t in tasks if t["kind"] == "BACKTEST"]

    return {
        "generated_from": "receipts table (live) joined to runs",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "n_tasks_with_data": len(tasks),
        "meets_min_3_bothways": len(tasks) >= 3,
        "has_trading_or_security": len(trading_or_security) >= 1,
        "backtested_tasks": backtests,
        "methodology": (
            "Every task ran both ways on the SAME data_snapshot: the agent policy "
            "and its named baseline (spec.md §9). Delta = agent_value - "
            "baseline_value in the agent's declared unit; 'favorable' respects the "
            "metric's higher_is_better. n and window length are shown per task. "
            "Tasks marked BACKTEST are historical replays — their replay method is "
            "stated and they are listed separately from live runs, never blended "
            "into one number."
        ),
        "caveats": [
            c for c in [
                None if len(tasks) >= 3 else
                f"Only {len(tasks)} task(s) have both-ways receipts; spec.md §10 "
                "wants ≥3. See `planned` for what is outstanding and why.",
                None if not backtests else
                f"{', '.join(backtests)} are BACKTEST replays, not live capital.",
            ] if c
        ],
        "tasks": tasks,
        "planned": planned,
    }


# --- PDF -----------------------------------------------------------------------

_PDF_SUBS = {
    "—": "-", "–": "-", "→": "->", "≥": ">=", "≤": "<=",
    "§": "sec.", "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": "...", "×": "x", "‑": "-",
}


def _ascii(txt: str) -> str:
    for k, v in _PDF_SUBS.items():
        txt = txt.replace(k, v)
    return txt.encode("latin-1", "replace").decode("latin-1")


def _pdf_line(pdf, txt: str, *, size: int = 10, style: str = "", gap: float = 5.0) -> None:
    pdf.set_font("Helvetica", style, size)
    pdf.multi_cell(0, gap, _ascii(txt), new_x="LMARGIN", new_y="NEXT")


def build_advantage_pdf() -> bytes:
    """Render build_advantage_report() to a one-file PDF (fpdf2, no system libs)."""
    from fpdf import FPDF

    rep = build_advantage_report()
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    _pdf_line(pdf, "Agent Advantage Report", size=18, style="B", gap=9)
    _pdf_line(pdf, f"generated {rep['generated_at']}  -  {rep['generated_from']}", size=8)
    _pdf_line(pdf, "", gap=2)
    _pdf_line(
        pdf,
        f"tasks with data: {rep['n_tasks_with_data']}   "
        f"min 3 both-ways: {'yes' if rep['meets_min_3_bothways'] else 'NO'}   "
        f"trading/security: {'yes' if rep['has_trading_or_security'] else 'NO'}",
        size=9, style="B",
    )
    for c in rep["caveats"]:
        _pdf_line(pdf, f"! {c}", size=8)
    _pdf_line(pdf, "", gap=2)
    _pdf_line(pdf, rep["methodology"], size=8)
    _pdf_line(pdf, "", gap=4)

    for t in rep["tasks"]:
        _pdf_line(pdf, f"{t['name']}  [{t['kind']}]", size=12, style="B", gap=7)
        _pdf_line(
            pdf,
            f"category {t['category']}  |  baseline {t['baseline']}  |  metric "
            f"{t['metric']} ({t['unit']}, {'higher' if t['higher_is_better'] else 'lower'} is better)",
            size=8,
        )
        _pdf_line(
            pdf,
            f"n={t['n']}   evaluation window="
            f"{t['evaluation_window_days'] if t['evaluation_window_days'] is not None else 'n/a'}d"
            f"   (runs spread over {t['receipts_span_days']}d, {t['first_at'][:19]} -> {t['last_at'][:19]})",
            size=8,
        )
        tm = t["time"]
        _pdf_line(
            pdf,
            f"time: agent median {tm['agent_median_seconds']}s (p90 {tm['agent_p90_seconds']}s)   "
            f"baseline median {tm['baseline_median_seconds']}s"
            + (" (HUMAN stopwatch)" if tm["baseline_is_human"] else "")
            + (f"   speedup {tm['speedup_x']}x" if tm["speedup_x"] else ""),
            size=8,
        )
        cost = t["cost"]
        _pdf_line(
            pdf,
            "cost: " + (cost["note"] or
                        f"gas {cost['agent_gas_bnb']} BNB  fees ${cost['protocol_fees_usd']}  "
                        f"agent fee ${cost['agent_fee_usd']}"),
            size=8,
        )
        oq = t["output_quality"]
        _pdf_line(
            pdf,
            f"output: avg delta {oq['avg_delta']}  median {oq['median_delta']}  "
            f"best {oq['best_delta']}  worst {oq['worst_delta']}  "
            f"win rate {oq['win_rate']} ({oq['wins']}W/{oq['losses']}L)  -> {oq['verdict']}",
            size=8,
        )
        if t["replay_method"]:
            _pdf_line(pdf, f"BACKTEST replay: {t['replay_method']}", size=8, style="I")
        _pdf_line(pdf, f"receipts ({len(t['outputs'])} shown):", size=8, style="B")
        for o in t["outputs"]:
            flag = "+" if o["favorable"] else "-"
            anc = " [anchored]" if o["anchored"] else ""
            _pdf_line(
                pdf,
                f"  {flag} {o['url']}  delta {o['delta']}  {o['created_at'][:19]}{anc}",
                size=7,
            )
        _pdf_line(pdf, "", gap=4)

    _pdf_line(pdf, "Planned tasks (spec.md 10)", size=12, style="B", gap=7)
    for p in rep["planned"]:
        _pdf_line(pdf, f"{p['agent_id']}  -  {p['task']}", size=8, style="B")
        _pdf_line(pdf, f"  baseline {p['baseline']}  |  {p['headline_metric']}", size=7)
        _pdf_line(pdf, f"  status: {p['status']}"
                  + (f"  -  {p['reason']}" if p["reason"] else ""), size=7)
        _pdf_line(pdf, "", gap=2)

    out = pdf.output()
    return bytes(out)
