"""Re-hire the single-shot agents (venus-guard, pcs-yield, bsc-sentry) a few
times so their receipt curves have more than n=1 (plan.md B / T-072 follow-up).

Unlike bnb-grid / pcs-rebalancer, these three have no continuous paper loop —
each hire is one independent both-ways run against live data, persisted
straight to the DB via the harness (same path `POST /hires` uses, no HTTP
round trip needed). Real inputs only (R2): venus-guard's account is the same
on-chain address already verified live in tests/test_venus_guard.py;
pcs-yield's capital/risk match tests/test_pcs_yield.py; bsc-sentry's target is
the CAKE address with the real T-072 manual_analyst row. Repeated bsc-sentry
runs are legitimate additional data points — the agent's wall-clock time
varies run to run against live RPC/anvil, same underlying baseline. Nothing
here is estimated or synthetic.

    export DATABASE_URL="<the Render/Neon postgres URL>"
    python scripts/rehire_singleshot.py --count 8 --interval 900
    python scripts/rehire_singleshot.py --count 5 --agent pcs-yield
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO / "services"))

from orchestrator import harness  # noqa: E402
from orchestrator.agents_factory import build_agent  # noqa: E402

# Real, previously-verified inputs (see module docstring) — not invented here.
VENUS_GUARD_INPUTS = {
    "account": "0x222170d4eb3987506a0453ea21e83274743eca14",
    "trigger_hf": 1.1,
    "buffer_token": "USDT",
    "buffer_amount": 3000,
}
PCS_YIELD_INPUTS = {"capital_usd": 5000, "risk": "balanced", "horizon_days": 30}
BSC_SENTRY_INPUTS = {"target": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82"}  # CAKE, T-072

JOBS = {
    "venus-guard": (1, VENUS_GUARD_INPUTS),
    "pcs-yield": (0, PCS_YIELD_INPUTS),
    "bsc-sentry": (0, BSC_SENTRY_INPUTS),
}


def _hire_once(agent_id: str) -> None:
    tier, inputs = JOBS[agent_id]
    agent = build_agent(agent_id)
    outcome = harness.run_hire(agent, tier, inputs, persist=True)
    print(f"[rehire] {agent_id}: delta={outcome.delta:+.4f} "
          f"favorable={outcome.favorable} receipt={outcome.receipt_id}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=8, help="hires per agent")
    ap.add_argument("--interval", type=int, default=900,
                     help="seconds between hires (spaces out live-data points)")
    ap.add_argument("--agent", choices=sorted(JOBS), default=None,
                     help="only re-hire this agent (default: both)")
    args = ap.parse_args()

    agent_ids = [args.agent] if args.agent else list(JOBS)
    print(f"[rehire] {args.count}x each of {agent_ids}, {args.interval}s apart", flush=True)

    for i in range(args.count):
        for agent_id in agent_ids:
            try:
                _hire_once(agent_id)
            except Exception:  # noqa: BLE001 — e.g. NotAtRisk, transient RPC error
                traceback.print_exc()
                print(f"[warn] {agent_id} hire {i + 1}/{args.count} failed; continuing", flush=True)
        if i < args.count - 1:
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[rehire] stopped", flush=True)
