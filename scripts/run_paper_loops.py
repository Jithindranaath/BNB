"""One process that cycles BOTH paper deployments (bnb-grid + pcs-rebalancer).

Two separate Python loops each load pandas + web3 + pydantic (~200 MB) — on a
memory-tight box that gets OOM-killed. This runs both agents' cycles in a single
interpreter. Resumes from the existing var/*.json (never resets).

    python scripts/run_paper_loops.py --interval 600
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO / "services"))

import run_grid
import run_rebalancer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=600)
    args = ap.parse_args()

    # resume existing deployments; create with sane defaults if missing
    grid_rec = run_grid._load_or_create(SimpleNamespace(
        reset=False, pair="BNB-USDT", capital=1000.0, levels=12, risk="balanced",
        backfill_hours=24))
    reb_rec = run_rebalancer._load_or_create(SimpleNamespace(
        reset=False, pool=run_rebalancer.DEFAULT_POOL, capital=5000.0, risk="balanced",
        backfill_hours=24))

    print(f"[paper] combined loop every {args.interval}s "
          f"(grid @cycle {grid_rec['cycles']}, rebalancer @cycle {reb_rec['cycles']})",
          flush=True)

    grid_alive = grid_rec.get("status") != "halted"
    while True:
        if grid_alive:
            try:
                grid_alive = run_grid._cycle(grid_rec)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                print("[warn] grid cycle failed; retry next interval", flush=True)
        try:
            run_rebalancer._cycle(reb_rec)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            print("[warn] rebalancer cycle failed; retry next interval", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[paper] stopped; deployment records kept", flush=True)
