"""Continuously run the bnb-grid Tier-1 PAPER deployment (plan.md T-040).

Each cycle re-simulates the grid from the deployment start to now over real
Binance prices and writes a receipt vs `hodl` (via the harness). The paper ledger
is a pure function of (klines since deploy, calibrated grid) — recomputed every
cycle, so there is no mutable ledger to corrupt. Stops only on the circuit
breaker or a fatal error.

    python scripts/run_grid.py --once                 # one cycle
    python scripts/run_grid.py --loop --interval 300  # run forever
    python scripts/run_grid.py --reset --backfill-hours 12 --loop

State: var/grid_deployment.json  (gitignored). Log: stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO / "services"))

from agents.bnb_grid.agent import BnbGridAgent
from orchestrator import harness

STATE = REPO / "var" / "grid_deployment.json"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_or_create(args) -> dict:
    if STATE.exists() and not args.reset:
        return json.loads(STATE.read_text())
    STATE.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "pair": args.pair,
        "capital_usd": args.capital,
        "grid_levels": args.levels,
        "risk": args.risk,
        "deployed_at_ms": _now_ms() - args.backfill_hours * 3_600_000,
        "created_at": datetime.now(tz=UTC).isoformat(),
        "status": "running",
        "cycles": 0,
        "halted": False,
    }
    STATE.write_text(json.dumps(rec, indent=2) + "\n")
    print(f"[deploy] new paper deployment: {rec['grid_levels']}-level {rec['risk']} grid on "
          f"{rec['pair']}, ${rec['capital_usd']}, backfilled {args.backfill_hours}h", flush=True)
    return rec


def _save(rec: dict) -> None:
    STATE.write_text(json.dumps(rec, indent=2) + "\n")


def _cycle(rec: dict) -> bool:
    """One evaluation cycle. Returns True if the deployment should keep running."""
    agent = BnbGridAgent(since_ms=rec["deployed_at_ms"])
    out = harness.run_hire(
        agent, tier=1,
        raw_inputs={"pair": rec["pair"], "capital_usd": rec["capital_usd"],
                    "grid_levels": rec["grid_levels"], "risk": rec["risk"]},
        persist=True,
    )
    st = out.agent_run.result.outputs["stats"]
    rec["cycles"] += 1
    rec["last_cycle_at"] = datetime.now(tz=UTC).isoformat()
    rec["last_receipt_id"] = str(out.receipt_id)
    rec["window_days"] = round(st["window_days"], 3)
    rec["net_pnl_usd"] = round(out.agent_value, 4)
    rec["hodl_pnl_usd"] = round(out.baseline_value, 4)
    rec["delta_vs_hodl_usd"] = round(out.delta, 4)
    rec["win_rate"] = st["win_rate"]
    rec["n_trades"] = st["n_trades"]
    rec["max_drawdown_pct"] = round(st["max_drawdown_pct"], 3)
    rec["capital_at_risk_usd"] = round(st["capital_at_risk_usd"], 2)
    rec["halted"] = st["halted"]

    print(
        f"[cycle {rec['cycles']:>4}] win={st['win_rate']:.0%} n={st['n_trades']:>3} "
        f"window={st['window_days']:.2f}d dd={st['max_drawdown_pct']:.2f}% "
        f"net=${out.agent_value:+.2f} hodl=${out.baseline_value:+.2f} "
        f"d=${out.delta:+.2f} receipt={out.receipt_id}",
        flush=True,
    )

    if st["halted"]:
        rec["status"] = "halted"
        rec["halt_reason"] = st["halt_reason"]
        _save(rec)
        print(f"[HALT] circuit breaker: {st['halt_reason']}", flush=True)
        return False
    _save(rec)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="BNB-USDT")
    ap.add_argument("--capital", type=float, default=1000.0)
    ap.add_argument("--levels", type=int, default=12)
    ap.add_argument("--risk", default="balanced", choices=["tight", "balanced", "wide"])
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--backfill-hours", type=int, default=12)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    rec = _load_or_create(args)
    if rec.get("status") == "halted" and not args.reset:
        print(f"[deploy] deployment is HALTED ({rec.get('halt_reason')}). "
              f"Use --reset to start a new one.", flush=True)
        return 1

    if not args.loop or args.once:
        try:
            _cycle(rec)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return 1
        return 0

    print(f"[deploy] looping every {args.interval}s (Ctrl+C to stop the loop; "
          f"the deployment record persists)", flush=True)
    try:
        while True:
            try:
                if not _cycle(rec):
                    return 0
            except Exception:  # noqa: BLE001 - a transient blip must not kill a multi-hour run
                traceback.print_exc()
                print("[warn] cycle failed; retrying next interval", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[deploy] loop stopped by user; record kept at var/grid_deployment.json", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
