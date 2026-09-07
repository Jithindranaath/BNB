"""Measure `venus_repay_borrow` gas on an Anvil BSC fork and merge it into
fixtures/gas_units.json (T-012 left it verified:false; T-044 fills it).

Lifecycle: supply vBNB -> enterMarkets -> borrow vUSDT -> approve -> repayBorrow.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from eth_utils import to_checksum_address

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO / "services"))

from agents.bsc_sentry.fork import anvil_fork
from data import reference

OUT = REPO / "fixtures" / "gas_units.json"
VBNB = "0xA07c5b74C9B40447a954e1466938b865b6BBea36"
VUSDT = "0xfD5840Cd36d94D7229439859C0112a4185BC0255"
COMPTROLLER = "0xfD36E2c2a6789Db23113685031d7F16329158384"
_MAXU = (1 << 256) - 1

_VBNB_ABI = [{"name": "mint", "type": "function", "stateMutability": "payable",
              "inputs": [], "outputs": [{"type": "uint256"}]}]
_VTOKEN_ABI = [
    {"name": "borrow", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"type": "uint256"}], "outputs": [{"type": "uint256"}]},
    {"name": "repayBorrow", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"type": "uint256"}], "outputs": [{"type": "uint256"}]},
    {"name": "borrowBalanceStored", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
]
_COMPTROLLER_ABI = [{"name": "enterMarkets", "type": "function", "stateMutability": "nonpayable",
                     "inputs": [{"type": "address[]"}], "outputs": [{"type": "uint256[]"}]}]


def main() -> int:
    usdt = to_checksum_address(reference.token_address("USDT"))
    with anvil_fork() as w3:
        acct = w3.eth.accounts[0]
        fork_block = w3.eth.block_number
        vbnb = w3.eth.contract(address=to_checksum_address(VBNB), abi=_VBNB_ABI + _VTOKEN_ABI)
        vusdt = w3.eth.contract(address=to_checksum_address(VUSDT), abi=_VTOKEN_ABI)
        comp = w3.eth.contract(address=to_checksum_address(COMPTROLLER), abi=_COMPTROLLER_ABI)
        USDT = w3.eth.contract(address=usdt, abi=reference.abi("erc20"))

        w3.eth.wait_for_transaction_receipt(
            vbnb.functions.mint().transact({"from": acct, "value": w3.to_wei(15, "ether")}))
        w3.eth.wait_for_transaction_receipt(
            comp.functions.enterMarkets([to_checksum_address(VBNB)]).transact({"from": acct}))
        w3.eth.wait_for_transaction_receipt(
            vusdt.functions.borrow(2000 * 10**18).transact({"from": acct}))
        assert USDT.functions.balanceOf(acct).call() >= 2000 * 10**18, "borrow did not deliver USDT"
        w3.eth.wait_for_transaction_receipt(
            USDT.functions.approve(to_checksum_address(VUSDT), _MAXU).transact({"from": acct}))

        gas = w3.eth.wait_for_transaction_receipt(
            vusdt.functions.repayBorrow(1000 * 10**18).transact({"from": acct})
        )["gasUsed"]
        remaining = vusdt.functions.borrowBalanceStored(acct).call()

    data = json.loads(OUT.read_text())
    data["ops"]["venus_repay_borrow"] = {"gas": int(gas), "verified": True}
    data["venus_measured_at_block"] = fork_block
    data["venus_measured_at"] = datetime.now(tz=UTC).isoformat()
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {OUT}")
    print(f"  venus_repay_borrow  {gas}   (debt left: {remaining / 1e18:.2f} USDT)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
