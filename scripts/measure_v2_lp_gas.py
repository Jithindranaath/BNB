"""Measure gas UNITS for PancakeSwap v2 add/remove-liquidity on an Anvil
BSC-mainnet fork (real txs, receipt.gasUsed). Merges `v2_add_liquidity` and
`v2_remove_liquidity` into fixtures/gas_units.json — used by pcs-yield's
amortised-gas term (spec.md §4.1). Same method as scripts/measure_gas.py /
measure_v3_gas.py; do NOT hardcode a guess (rule R2).

    python scripts/measure_v2_lp_gas.py
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

PORT = 8547
RPC = f"http://127.0.0.1:{PORT}"
OUT = REPO / "fixtures" / "gas_units.json"
_MAXU = (1 << 256) - 1

WBNB_ABI = [
    {"name": "deposit", "type": "function", "stateMutability": "payable", "inputs": [], "outputs": []},
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
]
ERC20_APPROVE = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
]
V2_ROUTER_ABI = [
    {"name": "swapExactTokensForTokens", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "address[]"},
                {"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "uint256[]"}]},
    {"name": "addLiquidity", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint256"}, {"type": "uint256"},
                {"type": "uint256"}, {"type": "uint256"}, {"type": "address"}, {"type": "uint256"}],
     "outputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}]},
    {"name": "removeLiquidity", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint256"}, {"type": "uint256"},
                {"type": "uint256"}, {"type": "address"}, {"type": "uint256"}],
     "outputs": [{"type": "uint256"}, {"type": "uint256"}]},
]
V2_FACTORY_ABI = [
    {"name": "getPair", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}, {"type": "address"}], "outputs": [{"type": "address"}]},
]


def _w3(url: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def _wait_port(port: int, timeout: float = 25.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise RuntimeError(f"anvil did not open port {port}")


def main() -> int:
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
        deadline = int(time.time()) + 3600

        wbnb = w3.to_checksum_address(reference.token_address("WBNB"))
        usdt = w3.to_checksum_address(reference.token_address("USDT"))
        router = w3.to_checksum_address(reference.contract("pancakeV2Router"))
        factory = w3.to_checksum_address(reference.contract("pancakeV2Factory"))

        WBNB = w3.eth.contract(address=wbnb, abi=WBNB_ABI)
        USDT = w3.eth.contract(address=usdt, abi=ERC20_APPROVE)
        ROUTER = w3.eth.contract(address=router, abi=V2_ROUTER_ABI)
        FACTORY = w3.eth.contract(address=factory, abi=V2_FACTORY_ABI)

        def gas_of(tx_hash) -> int:
            r = w3.eth.wait_for_transaction_receipt(tx_hash)
            if r["status"] != 1:
                raise RuntimeError(f"tx reverted: {tx_hash.hex()}")
            return r["gasUsed"]

        # fund: wrap 20 BNB, swap 10 -> USDT, approve router for both
        gas_of(WBNB.functions.deposit().transact({"from": acct, "value": w3.to_wei(20, "ether")}))
        gas_of(WBNB.functions.approve(router, _MAXU).transact({"from": acct}))
        gas_of(ROUTER.functions.swapExactTokensForTokens(
            w3.to_wei(10, "ether"), 0, [wbnb, usdt], acct, deadline).transact({"from": acct}))
        gas_of(USDT.functions.approve(router, _MAXU).transact({"from": acct}))

        usdt_bal = USDT.functions.balanceOf(acct).call()

        add_gas = gas_of(ROUTER.functions.addLiquidity(
            wbnb, usdt, w3.to_wei(5, "ether"), usdt_bal // 2, 0, 0, acct, deadline
        ).transact({"from": acct}))

        pair = w3.to_checksum_address(FACTORY.functions.getPair(wbnb, usdt).call())
        LP = w3.eth.contract(address=pair, abi=ERC20_APPROVE)
        lp_bal = LP.functions.balanceOf(acct).call()
        gas_of(LP.functions.approve(router, _MAXU).transact({"from": acct}))

        rm_gas = gas_of(ROUTER.functions.removeLiquidity(
            wbnb, usdt, lp_bal, 0, 0, acct, deadline
        ).transact({"from": acct}))

        # merge into the existing file
        data = json.loads(OUT.read_text()) if OUT.exists() else {"ops": {}}
        data["ops"]["v2_add_liquidity"] = {"gas": add_gas, "verified": True}
        data["ops"]["v2_remove_liquidity"] = {"gas": rm_gas, "verified": True}
        data["v2_lp_measured_at_block"] = fork_block
        data["v2_lp_measured_at"] = datetime.now(tz=UTC).isoformat()
        OUT.write_text(json.dumps(data, indent=2) + "\n")

        print(f"wrote {OUT}")
        print(f"  v2_add_liquidity     {add_gas}")
        print(f"  v2_remove_liquidity  {rm_gas}")
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
