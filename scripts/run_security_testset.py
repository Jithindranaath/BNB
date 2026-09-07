"""Run bsc-sentry over fixtures/security_testset.json and write the measured
claim to fixtures/security_results.json (spec.md §3.4).

  python scripts/run_security_testset.py [--limit-good N]

NOT a training run — this is a held-out labeled set. `good` = established BSC
tokens (should score OK/WARN). `synthetic_bad` = malicious contracts deployed on
the fork (should score CRITICAL). Reports precision / recall / FPR / n.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO / "services"))

from agents.bsc_sentry.agent import gather
from agents.bsc_sentry.fork import anvil_fork
from agents.bsc_sentry.scoring import score_report
from data import reference

SET = REPO / "fixtures" / "security_testset.json"
OUT = REPO / "fixtures" / "security_results.json"
_MAXU = (1 << 256) - 1
_LIQ_ABI = [
    {"name": "addLiquidityETH", "type": "function", "stateMutability": "payable",
     "inputs": [{"type": "address"}, {"type": "uint256"}, {"type": "uint256"},
                {"type": "uint256"}, {"type": "address"}, {"type": "uint256"}],
     "outputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}]},
]
_FACTORY_ABI = [
    {"name": "getPair", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}, {"type": "address"}], "outputs": [{"type": "address"}]},
]


def _artifact(name: str) -> dict:
    p = REPO / "contracts" / "out" / f"{name}.sol" / f"{name}.json"
    return json.loads(p.read_text())


def _predict(target: str, w3, *, fetch_source: bool) -> dict:
    checks = gather(target, w3, fetch_source=fetch_source)
    rep = score_report(target, checks)
    return rep.as_dict()


def _deploy_bad(w3, artifact_name: str):
    art = _artifact(artifact_name)
    dep = w3.eth.accounts[0]
    wbnb = w3.to_checksum_address(reference.token_address("WBNB"))
    router = w3.to_checksum_address(reference.contract("pancakeV2Router"))
    factory = w3.to_checksum_address(reference.contract("pancakeV2Factory"))

    C = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]["object"])
    addr = w3.eth.wait_for_transaction_receipt(
        C.constructor(10**24).transact({"from": dep})
    )["contractAddress"]
    tok = w3.eth.contract(address=addr, abi=art["abi"])
    r = w3.eth.contract(address=router, abi=art["abi"] + _LIQ_ABI)
    w3.eth.wait_for_transaction_receipt(tok.functions.approve(router, _MAXU).transact({"from": dep}))
    w3.eth.wait_for_transaction_receipt(
        r.functions.addLiquidityETH(addr, 500_000 * 10**18, 0, 0, dep, int(time.time()) + 1800)
        .transact({"from": dep, "value": w3.to_wei(10, "ether")})
    )
    f = w3.eth.contract(address=factory, abi=_FACTORY_ABI)
    pair = f.functions.getPair(addr, wbnb).call()
    w3.eth.wait_for_transaction_receipt(tok.functions.setPair(pair).transact({"from": dep}))
    return addr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-good", type=int, default=0, help="0 = all")
    args = ap.parse_args()

    spec = json.loads(SET.read_text())
    good = spec["good"]
    if args.limit_good:
        good = good[: args.limit_good]
    rows: list[dict] = []

    print(f"[good] {len(good)} tokens, a fresh fork each (public dataseed rate-limits "
          "a shared fork after ~10 tokens) ...", flush=True)
    for i, t in enumerate(good, 1):
        verdict, rep = "ERROR", {}
        for attempt in (1, 2):
            try:
                with anvil_fork() as w3:
                    rep = _predict(t["address"], w3, fetch_source=True)
                verdict = rep["verdict"]
                break
            except Exception as e:  # noqa: BLE001
                rep = {"error": f"{type(e).__name__}: {str(e)[:180]}"}
                time.sleep(3 * attempt)
        rows.append({"label": "good", "ref": t["symbol"], "address": t["address"],
                     "verdict": verdict, "hard_fails": rep.get("hard_fails", []),
                     "warnings": rep.get("warnings", []), "score": rep.get("score"),
                     "error": rep.get("error")})
        print(f"  {i:2}/{len(good)} {t['symbol']:6} -> {verdict} "
              f"{rep.get('hard_fails') or rep.get('error', '')}", flush=True)

    print(f"[synthetic_bad] {len(spec['synthetic_bad'])} contracts on a fresh fork ...", flush=True)
    with anvil_fork() as w3:
        for b in spec["synthetic_bad"]:
            addr = _deploy_bad(w3, b["contract"])
            rep = _predict(addr, w3, fetch_source=False)
            rows.append({"label": "bad", "ref": b["contract"], "address": addr,
                         "verdict": rep["verdict"], "hard_fails": rep["hard_fails"],
                         "score": rep["score"], "expected_hard_fail": b["expect_hard_fail"]})
            print(f"  {b['contract']:14} -> {rep['verdict']} {rep['hard_fails']}", flush=True)

    tp = sum(1 for r in rows if r["label"] == "bad" and r["verdict"] == "CRITICAL")
    fn = sum(1 for r in rows if r["label"] == "bad" and r["verdict"] != "CRITICAL")
    fp = sum(1 for r in rows if r["label"] == "good" and r["verdict"] == "CRITICAL")
    tn = sum(1 for r in rows if r["label"] == "good" and r["verdict"] in ("OK", "WARN"))
    err = sum(1 for r in rows if r["verdict"] == "ERROR")

    def _rate(a: int, b: int) -> float | None:
        return round(a / b, 4) if b else None

    results = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "n": len(rows),
        "n_good": sum(1 for r in rows if r["label"] == "good"),
        "n_bad": sum(1 for r in rows if r["label"] == "bad"),
        "confusion": {"tp": tp, "fn": fn, "fp": fp, "tn": tn, "errors": err},
        "precision": _rate(tp, tp + fp),
        "recall": _rate(tp, tp + fn),
        "false_positive_rate": _rate(fp, fp + tn),
        "method": "Anvil BSC-mainnet fork buy/sell simulation + on-chain checks + BscScan "
                  "source scan, scored by agents.bsc_sentry.scoring. 'bad' are synthetic "
                  "malicious contracts deployed with real PancakeSwap v2 liquidity; add real "
                  "rug post-mortem addresses to security_testset.json['bad'] to grow n.",
        "rows": rows,
    }
    OUT.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nwrote {OUT}")
    print(f"n={results['n']}  precision={results['precision']}  recall={results['recall']}  "
          f"FPR={results['false_positive_rate']}  confusion={results['confusion']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
