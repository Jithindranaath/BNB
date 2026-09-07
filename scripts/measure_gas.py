"""Measure gas UNITS for on-chain ops on an Anvil BSC-mainnet fork, by sending
real transactions and reading `receipt.gasUsed`. Writes fixtures/gas_units.json
with the fork block (spec.md §2, plan.md T-012 — do NOT hardcode a guess).

    python scripts/measure_gas.py

Ops that need a live LP position / borrow (v3 NPM mint/decrease/collect/burn,
venus repay) are left `verified: false` here and measured by the task that
builds them (T-042 / T-044).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))

from data import reference
from data.settings import settings


def _w3(url: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)  # BSC PoA
    return w3

PORT = 8546
RPC = f"http://127.0.0.1:{PORT}"
OUT = REPO / "fixtures" / "gas_units.json"

WBNB_ABI = [
    {"name": "deposit", "type": "function", "stateMutability": "payable", "inputs": [], "outputs": []},
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
]
V2_ROUTER_ABI = [
    {"name": "swapExactTokensForTokens", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "address[]"},
                {"type": "address"}, {"type": "uint256"}],
     "outputs": [{"type": "uint256[]"}]},
]


def _wait_port(port: int, timeout: float = 20.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise RuntimeError(f"anvil did not open port {port}")


def main() -> int:
    # Fork at HEAD (no --fork-block-number). Use fork_rpc_url — a dataseed that
    # serves recent state unauthenticated (PublicNode 403s archive reads once
    # head moves past the fork block). Gas units are block-insensitive; we record
    # the block anvil forked at.
    fork_url = settings().fork_rpc_url

    proc = subprocess.Popen(
        ["anvil", "--fork-url", fork_url, "--port", str(PORT), "--silent"],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        _wait_port(PORT)
        w3 = _w3(RPC)
        assert w3.is_connected()
        fork_block = w3.eth.block_number
        acct = w3.eth.accounts[0]

        wbnb = w3.to_checksum_address(reference.token_address("WBNB"))
        usdt = w3.to_checksum_address(reference.token_address("USDT"))
        router = w3.to_checksum_address(reference.contract("pancakeV2Router"))

        WBNB = w3.eth.contract(address=wbnb, abi=WBNB_ABI)
        ROUTER = w3.eth.contract(address=router, abi=V2_ROUTER_ABI)

        def gas_of(tx_hash) -> int:
            return w3.eth.wait_for_transaction_receipt(tx_hash)["gasUsed"]

        ops: dict[str, dict] = {}

        # 1. wrap 2 BNB -> WBNB
        ops["wrap_bnb"] = {"gas": gas_of(
            WBNB.functions.deposit().transact({"from": acct, "value": w3.to_wei(2, "ether")})
        ), "verified": True}

        # 2. approve router for WBNB
        maxu = (1 << 256) - 1
        ops["approve"] = {"gas": gas_of(
            WBNB.functions.approve(router, maxu).transact({"from": acct})
        ), "verified": True}

        # 3. v2 swap 0.5 WBNB -> USDT
        deadline = int(time.time()) + 3600
        ops["swap_v2"] = {"gas": gas_of(
            ROUTER.functions.swapExactTokensForTokens(
                w3.to_wei("0.5", "ether"), 0, [wbnb, usdt], acct, deadline
            ).transact({"from": acct})
        ), "verified": True}

        for op, note in {
            "v3_mint": "T-042 (NonfungiblePositionManager)",
            "v3_increase_liquidity": "T-042",
            "v3_decrease_liquidity": "T-042",
            "v3_collect": "T-042",
            "v3_burn": "T-042",
            "venus_repay_borrow": "T-044",
        }.items():
            ops[op] = {"gas": None, "verified": False, "note": f"measured in {note}"}

        OUT.write_text(json.dumps({
            "chain": "bsc-fork",
            "fork_of": fork_url.split("//")[-1].split("/")[0],
            "measured_at_block": fork_block,
            "measured_at": datetime.now(tz=UTC).isoformat(),
            "method": "real txs on an Anvil BSC-mainnet fork; receipt.gasUsed",
            "script": "scripts/measure_gas.py",
            "ops": ops,
        }, indent=2) + "\n")
        print(f"wrote {OUT}")
        for k, v in ops.items():
            print(f"  {k:24} {v['gas'] if v['verified'] else '(deferred)'}")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
