"""PancakeSwap v3 NonfungiblePositionManager execution (spec.md §6.3).

decreaseLiquidity -> collect -> burn -> mint, via web3. Used by:
  * scripts/measure_v3_gas.py  — on an Anvil fork, to fill the v3 gas units
  * PcsRebalancerAgent (Tier 2) — with a scoped session-key signer

T-004 found Hummingbot Gateway can also do this; this hand-rolled path is the
tested fallback (kept until Gateway is proven end-to-end on mainnet in a dry run).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from data import reference
from eth_utils import to_checksum_address
from web3 import Web3

# minimal NonfungiblePositionManager ABI
NPM_ABI = [
    {"name": "mint", "type": "function", "stateMutability": "payable",
     "inputs": [{"name": "params", "type": "tuple", "components": [
         {"name": "token0", "type": "address"}, {"name": "token1", "type": "address"},
         {"name": "fee", "type": "uint24"}, {"name": "tickLower", "type": "int24"},
         {"name": "tickUpper", "type": "int24"}, {"name": "amount0Desired", "type": "uint256"},
         {"name": "amount1Desired", "type": "uint256"}, {"name": "amount0Min", "type": "uint256"},
         {"name": "amount1Min", "type": "uint256"}, {"name": "recipient", "type": "address"},
         {"name": "deadline", "type": "uint256"}]}],
     "outputs": [{"name": "tokenId", "type": "uint256"}, {"name": "liquidity", "type": "uint128"},
                 {"name": "amount0", "type": "uint256"}, {"name": "amount1", "type": "uint256"}]},
    {"name": "increaseLiquidity", "type": "function", "stateMutability": "payable",
     "inputs": [{"name": "params", "type": "tuple", "components": [
         {"name": "tokenId", "type": "uint256"}, {"name": "amount0Desired", "type": "uint256"},
         {"name": "amount1Desired", "type": "uint256"}, {"name": "amount0Min", "type": "uint256"},
         {"name": "amount1Min", "type": "uint256"}, {"name": "deadline", "type": "uint256"}]}],
     "outputs": [{"name": "liquidity", "type": "uint128"}, {"name": "amount0", "type": "uint256"},
                 {"name": "amount1", "type": "uint256"}]},
    {"name": "decreaseLiquidity", "type": "function", "stateMutability": "payable",
     "inputs": [{"name": "params", "type": "tuple", "components": [
         {"name": "tokenId", "type": "uint256"}, {"name": "liquidity", "type": "uint128"},
         {"name": "amount0Min", "type": "uint256"}, {"name": "amount1Min", "type": "uint256"},
         {"name": "deadline", "type": "uint256"}]}],
     "outputs": [{"name": "amount0", "type": "uint256"}, {"name": "amount1", "type": "uint256"}]},
    {"name": "collect", "type": "function", "stateMutability": "payable",
     "inputs": [{"name": "params", "type": "tuple", "components": [
         {"name": "tokenId", "type": "uint256"}, {"name": "recipient", "type": "address"},
         {"name": "amount0Max", "type": "uint128"}, {"name": "amount1Max", "type": "uint128"}]}],
     "outputs": [{"name": "amount0", "type": "uint256"}, {"name": "amount1", "type": "uint256"}]},
    {"name": "burn", "type": "function", "stateMutability": "payable",
     "inputs": [{"name": "tokenId", "type": "uint256"}], "outputs": []},
    {"name": "positions", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "tokenId", "type": "uint256"}],
     "outputs": [{"type": "uint96"}, {"type": "address"}, {"type": "address"}, {"type": "address"},
                 {"type": "uint24"}, {"type": "int24"}, {"type": "int24"}, {"type": "uint128"},
                 {"type": "uint256"}, {"type": "uint256"}, {"type": "uint128"}, {"type": "uint128"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "tokenOfOwnerByIndex", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "uint256"}]},
]
_U128_MAX = (1 << 128) - 1
_U256_MAX = (1 << 256) - 1


def npm_contract(w3: Web3):
    return w3.eth.contract(
        address=to_checksum_address(reference.contract("pancakeV3PositionManager")), abi=NPM_ABI
    )


def _erc20(w3: Web3, addr: str):
    return w3.eth.contract(address=to_checksum_address(addr), abi=reference.abi("erc20"))


@dataclass
class PositionResult:
    token_id: int
    liquidity: int
    amount0: int
    amount1: int
    gas: dict[str, int]


def open_position(
    w3: Web3, sender: str, *, token0: str, token1: str, fee: int,
    tick_lower: int, tick_upper: int, amount0: int, amount1: int,
) -> PositionResult:
    npm = npm_contract(w3)
    npm_addr = npm.address
    for t, amt in ((token0, amount0), (token1, amount1)):
        if amt:
            w3.eth.wait_for_transaction_receipt(
                _erc20(w3, t).functions.approve(npm_addr, _U256_MAX).transact({"from": sender})
            )
    params = (to_checksum_address(token0), to_checksum_address(token1), fee,
              tick_lower, tick_upper, amount0, amount1, 0, 0,
              to_checksum_address(sender), int(time.time()) + 1800)
    sender = to_checksum_address(sender)
    rcpt = w3.eth.wait_for_transaction_receipt(
        npm.functions.mint(params).transact({"from": sender})
    )
    if rcpt["status"] != 1:
        raise RuntimeError("mint() reverted")
    # the freshly minted id = the sender's newest NPM token (ERC-721 Enumerable)
    bal = npm.functions.balanceOf(sender).call()
    token_id = int(npm.functions.tokenOfOwnerByIndex(sender, bal - 1).call())
    liq = int(npm.functions.positions(token_id).call()[7])
    return PositionResult(token_id, liq, amount0, amount1, {"v3_mint": rcpt["gasUsed"]})


def increase_liquidity(w3: Web3, sender: str, token_id: int, amount0: int, amount1: int) -> int:
    npm = npm_contract(w3)
    params = (token_id, amount0, amount1, 0, 0, int(time.time()) + 1800)
    rcpt = w3.eth.wait_for_transaction_receipt(
        npm.functions.increaseLiquidity(params).transact({"from": sender})
    )
    return rcpt["gasUsed"]


def close_position(w3: Web3, sender: str, token_id: int) -> dict[str, int]:
    """decreaseLiquidity(all) -> collect -> burn. Returns gasUsed per step."""
    npm = npm_contract(w3)
    liq = npm.functions.positions(token_id).call()[7]
    gas: dict[str, int] = {}

    dec = (token_id, int(liq), 0, 0, int(time.time()) + 1800)
    gas["v3_decrease_liquidity"] = w3.eth.wait_for_transaction_receipt(
        npm.functions.decreaseLiquidity(dec).transact({"from": sender})
    )["gasUsed"]

    col = (token_id, to_checksum_address(sender), _U128_MAX, _U128_MAX)
    gas["v3_collect"] = w3.eth.wait_for_transaction_receipt(
        npm.functions.collect(col).transact({"from": sender})
    )["gasUsed"]

    gas["v3_burn"] = w3.eth.wait_for_transaction_receipt(
        npm.functions.burn(token_id).transact({"from": sender})
    )["gasUsed"]
    return gas


def position_liquidity(w3: Web3, token_id: int) -> int:
    return int(npm_contract(w3).functions.positions(token_id).call()[7])
