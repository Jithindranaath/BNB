"""Batch unbatched receipts and anchor the merkle root via ReceiptAnchor.sol
(architecture.md §12, plan.md T-062).

    python scripts/anchor_receipts.py                 # local anvil (:8545), deploys the contract
    python scripts/anchor_receipts.py --rpc <bsc> ... # with ANCHOR_PRIVATE_KEY + RECEIPT_ANCHOR_ADDRESS

Proves the whole flow end to end: create_batch -> merkle root -> anchor() tx ->
BatchAnchored event -> a per-receipt proof verifies against the on-chain root.
A BSC-mainnet anchor just needs the two env vars + a funded low-value key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO / "services"))

from orchestrator import anchor
from orchestrator.anchor import ANCHOR_ABI

ARTIFACT = REPO / "contracts" / "out" / "ReceiptAnchor.sol" / "ReceiptAnchor.json"


def _w3(rpc: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(rpc))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default="http://127.0.0.1:8545")
    ap.add_argument("--min-size", type=int, default=1)
    args = ap.parse_args()

    key = os.environ.get("ANCHOR_PRIVATE_KEY", "").strip()
    addr = os.environ.get("RECEIPT_ANCHOR_ADDRESS", "").strip()

    bid = anchor.create_batch(min_size=args.min_size)
    if not bid:
        print("nothing to batch (no unbatched receipts)")
        return 0
    leaves = anchor.batch_leaves(bid)
    print(f"batch {bid}: {len(leaves)} receipts, root {anchor.merkle_root(leaves)}")

    w3 = _w3(args.rpc)
    assert w3.is_connected(), f"cannot reach {args.rpc}"

    if key and addr:
        account = Account.from_key(key)
        print(f"anchoring on {args.rpc} at {addr} as {account.address}")
        out = anchor.submit_batch(w3, account, addr, bid)
    else:
        if not ARTIFACT.exists():
            print("build the contract first: cd contracts && forge build")
            return 1
        art = json.loads(ARTIFACT.read_text())
        deployer = w3.eth.accounts[0]
        C = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]["object"])
        dep = w3.eth.wait_for_transaction_receipt(C.constructor().transact({"from": deployer}))
        anchor_addr = dep["contractAddress"]
        print(f"deployed ReceiptAnchor -> {anchor_addr} (local anvil; no mainnet key set)")
        out = anchor.submit_batch(w3, deployer, anchor_addr, bid)

    print(f"anchored: tx {out['tx']} block {out['block']}")

    # read the BatchAnchored event + verify one proof against its root
    c = w3.eth.contract(address=w3.to_checksum_address(out["anchor"]), abi=ANCHOR_ABI)
    evs = c.events.BatchAnchored().get_logs(from_block=out["block"], to_block=out["block"])
    assert evs, "no BatchAnchored event"
    onchain_root = "0x" + evs[0]["args"]["root"].hex()
    assert onchain_root == out["root"], f"root mismatch {onchain_root} != {out['root']}"

    proof, root = anchor.proof_for(_first_receipt_of_batch(bid))
    ok = anchor.verify_proof(_first_leaf(bid), proof or [], root or "")
    print(f"event root == batch root: OK   proof verifies: {ok}")
    return 0 if ok else 1


def _first_receipt_of_batch(bid: str) -> str:
    from orchestrator import db
    from sqlalchemy import text

    with db.session() as s:
        return str(s.execute(
            text("SELECT id FROM receipts WHERE batch_id = :b ORDER BY created_at, id LIMIT 1"),
            {"b": bid},
        ).scalar_one())


def _first_leaf(bid: str) -> str:
    return anchor.batch_leaves(bid)[0]


if __name__ == "__main__":
    raise SystemExit(main())
