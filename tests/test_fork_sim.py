"""T-030: the Anvil fork trade sim flags a honeypot as unsellable and a
known-good token as sellable, with the addresses cited.

  good token : CAKE  0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82  (reference/tokens.json)
  honeypot   : HoneypotToken deployed on the fork with real PancakeSwap v2
               liquidity — deterministic, doesn't depend on some rug still
               having a pool.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from agents.bsc_sentry.fork import anvil_fork, simulate_trade
from data import reference
from eth_utils import to_checksum_address

pytestmark = pytest.mark.live

REPO = Path(__file__).resolve().parents[1]
HPT_ARTIFACT = REPO / "contracts" / "out" / "HoneypotToken.sol" / "HoneypotToken.json"
CAKE = "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82"

_ROUTER_LIQ_ABI = [
    {"name": "addLiquidityETH", "type": "function", "stateMutability": "payable",
     "inputs": [{"type": "address"}, {"type": "uint256"}, {"type": "uint256"},
                {"type": "uint256"}, {"type": "address"}, {"type": "uint256"}],
     "outputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}]},
]
_FACTORY_ABI = [
    {"name": "getPair", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}, {"type": "address"}], "outputs": [{"type": "address"}]},
]
_MAXU = (1 << 256) - 1


@pytest.fixture(scope="module")
def hpt_artifact() -> dict:
    if not HPT_ARTIFACT.exists():
        subprocess.run(["forge", "build"], cwd=REPO / "contracts", check=True,
                       capture_output=True)
    if not HPT_ARTIFACT.exists():
        pytest.skip("HoneypotToken not built (need foundry: cd contracts && forge build)")
    return json.loads(HPT_ARTIFACT.read_text())


def test_known_good_token_is_sellable():
    with anvil_fork() as w3:
        res = simulate_trade(CAKE, w3)
    assert res.pair_found is True
    assert res.buyable is True
    assert res.sellable is True
    assert res.is_honeypot is False
    assert (res.sell_tax_pct or 0) < 0.05  # CAKE has no transfer tax
    assert res.gas_buy and res.gas_sell


def test_deployed_honeypot_is_flagged_unsellable(hpt_artifact):
    with anvil_fork() as w3:
        deployer = w3.eth.accounts[0]
        wbnb = to_checksum_address(reference.token_address("WBNB"))
        router_addr = to_checksum_address(reference.contract("pancakeV2Router"))
        factory_addr = to_checksum_address(reference.contract("pancakeV2Factory"))

        Hpt = w3.eth.contract(abi=hpt_artifact["abi"], bytecode=hpt_artifact["bytecode"]["object"])
        tx = Hpt.constructor(10**24).transact({"from": deployer})
        hpt_addr = w3.eth.wait_for_transaction_receipt(tx)["contractAddress"]
        hpt = w3.eth.contract(address=hpt_addr, abi=hpt_artifact["abi"])

        router = w3.eth.contract(address=router_addr, abi=hpt_artifact["abi"] + _ROUTER_LIQ_ABI)
        w3.eth.wait_for_transaction_receipt(
            hpt.functions.approve(router_addr, _MAXU).transact({"from": deployer})
        )
        deadline = int(time.time()) + 1800
        w3.eth.wait_for_transaction_receipt(
            router.functions.addLiquidityETH(
                hpt_addr, 500_000 * 10**18, 0, 0, deployer, deadline
            ).transact({"from": deployer, "value": w3.to_wei(10, "ether")})
        )
        factory = w3.eth.contract(address=factory_addr, abi=_FACTORY_ABI)
        pair = factory.functions.getPair(hpt_addr, wbnb).call()
        assert int(pair, 16) != 0
        w3.eth.wait_for_transaction_receipt(
            hpt.functions.setPair(pair).transact({"from": deployer})
        )

        res = simulate_trade(hpt_addr, w3, trader_index=1)

    assert res.pair_found is True
    assert res.buyable is True           # buying works — that's the trap
    assert res.sellable is False         # selling reverts
    assert res.is_honeypot is True
    assert res.sell_revert and ("HONEYPOT" in res.sell_revert or "revert" in res.sell_revert.lower())
