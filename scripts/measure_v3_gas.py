"""Measure the PancakeSwap v3 NonfungiblePositionManager gas UNITS on an Anvil
BSC-mainnet fork by running a real position lifecycle, and merge them into
fixtures/gas_units.json (plan.md T-012 left these verified:false; T-043 fills them).

    python scripts/measure_v3_gas.py

Lifecycle: wrap BNB -> swap half for USDT -> mint an in-range WBNB/USDT position
-> increaseLiquidity -> decreaseLiquidity(all) -> collect -> burn.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from eth_utils import to_checksum_address

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO / "services"))

from agents.bsc_sentry.fork import anvil_fork
from agents.pcs_rebalancer.npm import (
    close_position,
    increase_liquidity,
    open_position,
)
from agents.pcs_rebalancer.range import snap_down, snap_up
from data import reference

OUT = REPO / "fixtures" / "gas_units.json"
_MAXU = (1 << 256) - 1
FEE = 500

_ROUTER_ABI = [
    {"name": "swapExactTokensForTokens", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "address[]"},
                {"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "uint256[]"}]},
]
_WBNB_ABI = reference.abi("erc20") + [
    {"name": "deposit", "type": "function", "stateMutability": "payable", "inputs": [], "outputs": []},
]
_POOL_ABI = [
    {"name": "slot0", "type": "function", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint160"}, {"type": "int24"}, {"type": "uint16"}, {"type": "uint16"},
                 {"type": "uint16"}, {"type": "uint32"}, {"type": "bool"}]},
    {"name": "tickSpacing", "type": "function", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "int24"}]},
]
_FACTORY_ABI = [
    {"name": "getPool", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint24"}],
     "outputs": [{"type": "address"}]},
]


def main() -> int:
    wbnb = to_checksum_address(reference.token_address("WBNB"))
    usdt = to_checksum_address(reference.token_address("USDT"))
    router = to_checksum_address(reference.contract("pancakeV2Router"))
    factory3 = to_checksum_address(reference.contract("pancakeV3Factory"))
    token0, token1 = sorted([wbnb, usdt], key=lambda a: int(a, 16))

    with anvil_fork() as w3:
        acct = w3.eth.accounts[0]
        fork_block = w3.eth.block_number
        W = w3.eth.contract(address=wbnb, abi=_WBNB_ABI)
        R = w3.eth.contract(address=router, abi=_ROUTER_ABI)

        w3.eth.wait_for_transaction_receipt(
            W.functions.deposit().transact({"from": acct, "value": w3.to_wei(20, "ether")}))
        w3.eth.wait_for_transaction_receipt(
            W.functions.approve(router, _MAXU).transact({"from": acct}))
        w3.eth.wait_for_transaction_receipt(
            R.functions.swapExactTokensForTokens(
                w3.to_wei(10, "ether"), 0, [wbnb, usdt], acct, int(time.time()) + 1800
            ).transact({"from": acct}))

        pool = w3.eth.contract(
            address=w3.eth.contract(address=factory3, abi=_FACTORY_ABI)
            .functions.getPool(wbnb, usdt, FEE).call(),
            abi=_POOL_ABI,
        )
        tick = pool.functions.slot0().call()[1]
        spacing = pool.functions.tickSpacing().call()
        tick_lower = snap_down(tick - 30 * spacing, spacing)
        tick_upper = snap_up(tick + 30 * spacing, spacing)

        bal0 = w3.eth.contract(address=token0, abi=reference.abi("erc20")).functions.balanceOf(acct).call()
        bal1 = w3.eth.contract(address=token1, abi=reference.abi("erc20")).functions.balanceOf(acct).call()
        amt0, amt1 = bal0 // 4, bal1 // 4

        pos = open_position(w3, acct, token0=token0, token1=token1, fee=FEE,
                            tick_lower=tick_lower, tick_upper=tick_upper,
                            amount0=amt0, amount1=amt1)
        gas = dict(pos.gas)
        gas["v3_increase_liquidity"] = increase_liquidity(
            w3, acct, pos.token_id, bal0 // 8, bal1 // 8)
        gas.update(close_position(w3, acct, pos.token_id))

    data = json.loads(OUT.read_text()) if OUT.exists() else {"ops": {}}
    for op, g in gas.items():
        data["ops"][op] = {"gas": int(g), "verified": True}
    data["v3_measured_at_block"] = fork_block
    data["v3_measured_at"] = datetime.now(tz=UTC).isoformat()
    OUT.write_text(json.dumps(data, indent=2) + "\n")

    print(f"wrote {OUT}")
    for op in ("v3_mint", "v3_increase_liquidity", "v3_decrease_liquidity", "v3_collect", "v3_burn"):
        print(f"  {op:24} {data['ops'][op]['gas']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
