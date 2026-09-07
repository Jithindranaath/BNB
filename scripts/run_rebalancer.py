"""Continuously run the pcs-rebalancer Tier-1 PAPER deployment (plan.md T-042).

Each cycle re-simulates the rebalancer from the deployment start to now over the
pool's real price path and writes a receipt vs `static_range` (via the harness).
The decision log — including every *hold* with its arithmetic (§6.2) — rides in
the receipt's outputs.

    python scripts/run_rebalancer.py --once
    python scripts/run_rebalancer.py --loop --interval 900
    python scripts/run_rebalancer.py --reset --pool 0x36696169... --capital 5000 --loop

State: var/rebalancer_deployment.json (gitignored). Log: stdout.
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

from agents.pcs_rebalancer.agent import PcsRebalancerAgent, UnsupportedPool
from orchestrator import harness

STATE = REPO / "var" / "rebalancer_deployment.json"
DEFAULT_POOL = "0x36696169C63e42cd08ce11f5deeBbCeBae652050"  # WBNB/USDT 0.05%


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_or_create(args) -> dict:
    if STATE.exists() and not args.reset:
        return json.loads(STATE.read_text())
    STATE.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "pool": args.pool, "capital_usd": args.capital, "risk": args.risk,
        "deployed_at_ms": _now_ms() - args.backfill_hours * 3_600_000,
        "created_at": datetime.now(tz=UTC).isoformat(),
        "status": "running", "cycles": 0,
    }
    STATE.write_text(json.dumps(rec, indent=2) + "\n")
    print(f"[deploy] new paper deployment: {rec['risk']} range on pool {rec['pool']}, "
          f"${rec['capital_usd']}, backfilled {args.backfill_hours}h", flush=True)
    return rec


def _cycle(rec: dict) -> bool:
    agent = PcsRebalancerAgent(since_ms=rec["deployed_at_ms"])
    out = harness.run_hire(
        agent, tier=1,
        raw_inputs={"pool": rec["pool"], "capital_usd": rec["capital_usd"], "risk": rec["risk"]},
        persist=True,
    )
    o = out.agent_run.result.outputs
    st = o["stats"]
    rec["cycles"] += 1
    rec["last_cycle_at"] = datetime.now(tz=UTC).isoformat()
    rec["last_receipt_id"] = str(out.receipt_id)
    rec["net_fees_usd"] = round(out.agent_value, 4)
    rec["static_range_usd"] = round(out.baseline_value, 4)
    rec["delta_vs_static_usd"] = round(out.delta, 4)
    rec["n_rebalances"] = st["n_rebalances"]
    rec["n_holds"] = st["n_holds"]
    rec["in_range_fraction"] = round(st["in_range_fraction"], 3)
    rec["window_days"] = round(st["window_days"], 3)
    STATE.write_text(json.dumps(rec, indent=2) + "\n")

    last_hold = next((d for d in reversed(o["decisions"]) if d["act"] is False), None)
    print(
        f"[cycle {rec['cycles']:>4}] window={st['window_days']:.2f}d "
        f"rebal={st['n_rebalances']} hold={st['n_holds']} inrange={st['in_range_fraction']:.0%} "
        f"net=${out.agent_value:+.2f} static=${out.baseline_value:+.2f} d=${out.delta:+.2f} "
        f"receipt={out.receipt_id}",
        flush=True,
    )
    if last_hold:
        print(f"           last hold: {last_hold['reason']}", flush=True)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default=DEFAULT_POOL)
    ap.add_argument("--capital", type=float, default=5000.0)
    ap.add_argument("--risk", default="balanced", choices=["tight", "balanced", "wide"])
    ap.add_argument("--interval", type=int, default=900)
    ap.add_argument("--backfill-hours", type=int, default=24)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    rec = _load_or_create(args)
    run = _cycle

    if not args.loop or args.once:
        try:
            run(rec)
        except UnsupportedPool as e:
            print(f"[error] {e}", flush=True)
            return 1
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return 1
        return 0

    print(f"[deploy] looping every {args.interval}s", flush=True)
    try:
        while True:
            try:
                run(rec)
            except Exception:  # noqa: BLE001 - a blip must not kill a multi-hour run
                traceback.print_exc()
                print("[warn] cycle failed; retrying next interval", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[deploy] loop stopped; record kept", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
