"""T-043: the NonfungiblePositionManager path opens, adjusts, and closes a real
PancakeSwap v3 position — proven on an Anvil BSC fork (a funded mainnet dry run
needs a scoped session key). scripts/measure_v3_gas.py writes the gas units.
"""

from __future__ import annotations

import time

import pytest
from agents.bsc_sentry.fork import anvil_fork
from agents.pcs_rebalancer.npm import (
    close_position,
    increase_liquidity,
    npm_contract,
    open_position,
    position_liquidity,
)
from agents.pcs_rebalancer.range import snap_down, snap_up
from data import reference
from eth_utils import to_checksum_address

pytestmark = pytest.mark.live

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


def test_v3_position_open_adjust_close_on_fork():
    wbnb = to_checksum_address(reference.token_address("WBNB"))
    usdt = to_checksum_address(reference.token_address("USDT"))
    router = to_checksum_address(reference.contract("pancakeV2Router"))
    factory3 = to_checksum_address(reference.contract("pancakeV3Factory"))
    token0, token1 = sorted([wbnb, usdt], key=lambda a: int(a, 16))

    with anvil_fork() as w3:
        acct = w3.eth.accounts[0]
        W = w3.eth.contract(address=wbnb, abi=_WBNB_ABI)
        R = w3.eth.contract(address=router, abi=_ROUTER_ABI)
        w3.eth.wait_for_transaction_receipt(
            W.functions.deposit().transact({"from": acct, "value": w3.to_wei(15, "ether")}))
        w3.eth.wait_for_transaction_receipt(
            W.functions.approve(router, _MAXU).transact({"from": acct}))
        w3.eth.wait_for_transaction_receipt(
            R.functions.swapExactTokensForTokens(
                w3.to_wei(7, "ether"), 0, [wbnb, usdt], acct, int(time.time()) + 1800
            ).transact({"from": acct}))

        pool_addr = w3.eth.contract(address=factory3, abi=_FACTORY_ABI).functions.getPool(
            wbnb, usdt, FEE).call()
        pool = w3.eth.contract(address=pool_addr, abi=_POOL_ABI)
        tick = pool.functions.slot0().call()[1]
        sp = pool.functions.tickSpacing().call()
        lo, hi = snap_down(tick - 25 * sp, sp), snap_up(tick + 25 * sp, sp)

        e0 = w3.eth.contract(address=token0, abi=reference.abi("erc20"))
        e1 = w3.eth.contract(address=token1, abi=reference.abi("erc20"))
        b0, b1 = e0.functions.balanceOf(acct).call(), e1.functions.balanceOf(acct).call()

        npm = npm_contract(w3)
        n_before = npm.functions.balanceOf(acct).call()

        pos = open_position(w3, acct, token0=token0, token1=token1, fee=FEE,
                            tick_lower=lo, tick_upper=hi, amount0=b0 // 4, amount1=b1 // 4)
        assert pos.token_id > 0 and pos.liquidity > 0
        assert pos.gas["v3_mint"] > 100_000
        assert npm.functions.balanceOf(acct).call() == n_before + 1     # opened
        liq_after_open = position_liquidity(w3, pos.token_id)

        increase_liquidity(w3, acct, pos.token_id, b0 // 8, b1 // 8)
        assert position_liquidity(w3, pos.token_id) > liq_after_open    # adjusted up

        gas = close_position(w3, acct, pos.token_id)                    # decrease -> collect -> burn
        assert npm.functions.balanceOf(acct).call() == n_before        # NFT burned -> closed
        assert set(gas) == {"v3_decrease_liquidity", "v3_collect", "v3_burn"}
        assert all(g > 0 for g in gas.values())
