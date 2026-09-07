"""Anvil BSC-fork trade simulation — the core of bsc-sentry (spec.md §3.2).

Fork BSC at head, give a fresh account WBNB, **buy** the target via the
PancakeSwap v2 router, then **attempt to sell** it back. Sell reverts -> honeypot.
Sell returns materially less than the router quoted -> transfer tax. This can't be
faked and no static analysis matches it.

We fund the trader by wrapping BNB from an Anvil pre-funded account rather than
impersonating a named whale — same effect, no hard-coded whale address (R1).
"""

from __future__ import annotations

import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from data import reference
from data.settings import settings
from eth_utils import to_checksum_address
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

_ROUTER_ABI = [
    {"name": "getAmountsOut", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "uint256"}, {"type": "address[]"}], "outputs": [{"type": "uint256[]"}]},
    {"name": "swapExactTokensForTokensSupportingFeeOnTransferTokens", "type": "function",
     "stateMutability": "nonpayable",
     "inputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "address[]"},
                {"type": "address"}, {"type": "uint256"}], "outputs": []},
]
_FACTORY_ABI = [
    {"name": "getPair", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}, {"type": "address"}], "outputs": [{"type": "address"}]},
]
_WBNB_ABI = reference.abi("erc20") + [
    {"name": "deposit", "type": "function", "stateMutability": "payable", "inputs": [], "outputs": []},
]
_MAXU = (1 << 256) - 1


@dataclass
class ForkSimResult:
    target: str
    pair_found: bool
    buyable: bool | None = None
    sellable: bool | None = None
    buy_tax_pct: float | None = None
    sell_tax_pct: float | None = None
    bought_raw: int = 0
    sold_for_wbnb_raw: int = 0
    gas_buy: int | None = None
    gas_sell: int | None = None
    buy_revert: str | None = None
    sell_revert: str | None = None
    fork_block: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_honeypot(self) -> bool:
        return self.pair_found and self.buyable is True and self.sellable is False

    def evidence(self) -> dict[str, Any]:
        return {
            "fork_block": self.fork_block,
            "pair_found": self.pair_found,
            "buyable": self.buyable,
            "sellable": self.sellable,
            "buy_tax_pct": self.buy_tax_pct,
            "sell_tax_pct": self.sell_tax_pct,
            "bought_raw": str(self.bought_raw),
            "sold_for_wbnb_raw": str(self.sold_for_wbnb_raw),
            "gas_buy": self.gas_buy,
            "gas_sell": self.gas_sell,
            "buy_revert": self.buy_revert,
            "sell_revert": self.sell_revert,
            "notes": self.notes,
        }


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def anvil_fork(block: int | None = None, *, fork_url: str | None = None):
    """Yield a Web3 connected to a fresh `anvil --fork-url` node; kill it on exit."""
    url = fork_url or settings().fork_rpc_url
    port = _free_port()
    cmd = ["anvil", "--fork-url", url, "--port", str(port), "--silent"]
    if block is not None:
        cmd += ["--fork-block-number", str(block)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.3)
        else:
            raise RuntimeError("anvil fork did not start")
        w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}", request_kwargs={"timeout": 60}))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        if not w3.is_connected():
            raise RuntimeError("anvil fork not reachable")
        yield w3
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _gas(w3: Web3, tx_hash) -> int:
    return w3.eth.wait_for_transaction_receipt(tx_hash)["gasUsed"]


def simulate_trade(
    token: str,
    w3: Web3,
    *,
    trader_index: int = 1,
    amount_wbnb: str = "1",
) -> ForkSimResult:
    """Buy `amount_wbnb` WBNB worth of `token`, then try to sell all of it back."""
    token = to_checksum_address(token)
    trader = w3.eth.accounts[trader_index]
    wbnb_addr = to_checksum_address(reference.token_address("WBNB"))
    router_addr = to_checksum_address(reference.contract("pancakeV2Router"))
    factory_addr = to_checksum_address(reference.contract("pancakeV2Factory"))

    wbnb = w3.eth.contract(address=wbnb_addr, abi=_WBNB_ABI)
    router = w3.eth.contract(address=router_addr, abi=_ROUTER_ABI)
    factory = w3.eth.contract(address=factory_addr, abi=_FACTORY_ABI)
    erc20 = w3.eth.contract(address=token, abi=reference.abi("erc20"))

    res = ForkSimResult(target=token, pair_found=False, fork_block=w3.eth.block_number)

    pair = factory.functions.getPair(token, wbnb_addr).call()
    if int(pair, 16) == 0:
        res.notes.append("no PancakeSwap v2 pair with WBNB — cannot simulate a trade")
        return res
    res.pair_found = True

    amount_in = w3.to_wei(amount_wbnb, "ether")
    if wbnb.functions.balanceOf(trader).call() < amount_in:
        _gas(w3, wbnb.functions.deposit().transact({"from": trader, "value": amount_in * 4}))
    _gas(w3, wbnb.functions.approve(router_addr, _MAXU).transact({"from": trader}))

    try:
        res.bought_raw = router.functions.getAmountsOut(amount_in, [wbnb_addr, token]).call()[-1]
    except Exception as e:  # noqa: BLE001
        res.notes.append(f"getAmountsOut(buy) failed: {e}")
    expected_buy = res.bought_raw or None

    # --- BUY ---
    deadline = int(time.time()) + 1800
    before = erc20.functions.balanceOf(trader).call()
    try:
        res.gas_buy = _gas(w3, router.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
            amount_in, 0, [wbnb_addr, token], trader, deadline
        ).transact({"from": trader}))
    except Exception as e:  # noqa: BLE001
        res.buyable = False
        res.buy_revert = str(e)[:300]
        return res
    bought = erc20.functions.balanceOf(trader).call() - before
    res.bought_raw = bought
    res.buyable = bought > 0
    if expected_buy and bought >= 0:
        res.buy_tax_pct = max(0.0, 1.0 - bought / expected_buy)
    if not res.buyable:
        res.notes.append("buy returned 0 tokens")
        return res

    # --- SELL ---
    try:
        erc20.functions.approve(router_addr, _MAXU).transact({"from": trader})
    except Exception as e:  # noqa: BLE001
        res.sellable = False
        res.sell_revert = f"approve() reverted: {str(e)[:200]}"
        return res

    expected_sell = None
    try:
        expected_sell = router.functions.getAmountsOut(bought, [token, wbnb_addr]).call()[-1]
    except Exception as e:  # noqa: BLE001
        res.notes.append(f"getAmountsOut(sell) failed: {e}")

    w_before = wbnb.functions.balanceOf(trader).call()
    try:
        res.gas_sell = _gas(w3, router.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
            bought, 0, [token, wbnb_addr], trader, deadline
        ).transact({"from": trader}))
    except Exception as e:  # noqa: BLE001
        res.sellable = False
        res.sell_revert = str(e)[:300]
        return res
    got = wbnb.functions.balanceOf(trader).call() - w_before
    res.sold_for_wbnb_raw = got
    res.sellable = got > 0
    if expected_sell and got >= 0:
        res.sell_tax_pct = max(0.0, 1.0 - got / expected_sell)
    if not res.sellable:
        res.notes.append("sell tx succeeded but returned 0 WBNB")
    return res


def run_fork_check(token: str, *, block: int | None = None) -> ForkSimResult:
    """Convenience: spin up a fork, simulate, tear down."""
    with anvil_fork(block=block) as w3:
        return simulate_trade(token, w3)
