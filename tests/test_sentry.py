"""T-031: bsc-sentry full check suite + scoring.

Pure scoring tests are fast; the two end-to-end tests fork BSC (`-m live`).
Every check must carry evidence — asserted throughout (spec.md §3.3).
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from agents.base import Observation, canonical_hash
from agents.bsc_sentry.agent import BscSentryAgent, gather
from agents.bsc_sentry.fork import anvil_fork
from agents.bsc_sentry.scoring import Check, score_report
from data import reference
from eth_utils import to_checksum_address

REPO = Path(__file__).resolve().parents[1]
HPT_ARTIFACT = REPO / "contracts" / "out" / "HoneypotToken.sol" / "HoneypotToken.json"
CAKE = "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82"
_MAXU = (1 << 256) - 1


# --- pure scoring ----------------------------------------------------

def _clean_checks() -> list[Check]:
    return [
        Check("honeypot", "pass", 1.0, {"sellable": True}, "bought and sold back"),
        Check("transfer_tax", "pass", 1.0, {"sell_tax_pct": 0.0}, "no tax"),
        Check("ownership", "pass", 1.0, {"renounced": True}, "renounced"),
        Check("dangerous_functions", "pass", 1.0, {"matched": []}, "none"),
        Check("lp_lock", "pass", 1.0, {"lp_burned_pct": 1.0}, "burned"),
        Check("source_verified", "pass", 1.0, {"verified": True}, "verified"),
        Check("upgradeable_proxy", "pass", 1.0, {"impl_slot": "0x0"}, "not a proxy"),
        Check("contract_age", "pass", 1.0, {"age_days_approx": 400}, "old"),
    ]


def test_clean_token_scores_ok():
    r = score_report("0xGOOD", _clean_checks())
    assert r.verdict == "OK" and r.score >= 75 and r.hard_fails == []


def test_honeypot_hard_fail_forces_critical():
    checks = _clean_checks()
    checks[0] = Check("honeypot", "fail", 0.0, {"sellable": False, "sell_revert": "..."},
                      "sell reverted", hard_fail=True)
    r = score_report("0xBAD", checks)
    assert r.verdict == "CRITICAL" and "honeypot" in r.hard_fails and r.score <= 10


def test_sell_tax_over_25pct_hard_fails():
    checks = _clean_checks()
    checks[1] = Check("transfer_tax", "fail", 0.0, {"sell_tax_pct": 0.4},
                      "sell tax 40%", hard_fail=True)
    r = score_report("0xTAX", checks)
    assert r.verdict == "CRITICAL" and "transfer_tax" in r.hard_fails


def test_eoa_mint_on_unverified_source_is_a_hard_fail():
    checks = _clean_checks()
    checks[2] = Check("ownership", "warn", 0.4,
                      {"owner": "0xabc", "renounced": False, "owner_code_size": 0}, "EOA owner")
    checks[3] = Check("dangerous_functions", "warn", 0.6, {"matched": ["mint"]}, "mint present")
    checks[5] = Check("source_verified", "warn", 0.3, {"verified": False}, "unverified")
    r = score_report("0xMINT", checks)
    assert "unrenounced_mint_unverified" in r.hard_fails and r.verdict == "CRITICAL"


def test_eoa_mint_on_verified_source_is_a_warning_not_critical():
    # Binance-Peg tokens (verified, EOA-held mint) — a heavy warn, not auto-CRITICAL
    checks = _clean_checks()
    checks[2] = Check("ownership", "warn", 0.4,
                      {"owner": "0xabc", "renounced": False, "owner_code_size": 0}, "EOA owner")
    checks[3] = Check("dangerous_functions", "warn", 0.6, {"matched": ["mint"]}, "mint present")
    r = score_report("0xPEG", checks)  # _clean_checks source_verified is verified=True
    assert "mint_by_eoa_verified" in r.warnings
    assert not r.hard_fails and r.verdict != "CRITICAL"


def test_mint_from_a_contract_owner_is_not_flagged():
    # legit reward tokens (e.g. CAKE -> MasterChef) mint from a contract
    checks = _clean_checks()
    checks[2] = Check("ownership", "warn", 0.7,
                      {"owner": "0xMC", "renounced": False, "owner_code_size": 12345}, "contract owner")
    checks[3] = Check("dangerous_functions", "warn", 0.6, {"matched": ["mint"]}, "mint present")
    r = score_report("0xCAKE", checks)
    assert not r.hard_fails and not r.warnings


def test_every_check_line_carries_evidence():
    r = score_report("0xGOOD", _clean_checks())
    for c in r.as_dict()["checks"]:
        assert isinstance(c["evidence"], dict) and c["evidence"], f"{c['name']} has no evidence"


# --- end to end (fork) --------------------------------------------

@pytest.fixture(scope="module")
def hpt_artifact() -> dict:
    if not HPT_ARTIFACT.exists():
        subprocess.run(["forge", "build"], cwd=REPO / "contracts", check=True, capture_output=True)
    if not HPT_ARTIFACT.exists():
        pytest.skip("HoneypotToken not built")
    return json.loads(HPT_ARTIFACT.read_text())


@pytest.mark.live
def test_full_report_on_known_good_token():
    agent = BscSentryAgent()
    obs = agent.observe({"target": CAKE})
    report = agent.decide(obs).params["report"]

    names = {c["name"] for c in report["checks"]}
    assert {"honeypot", "transfer_tax", "ownership", "upgradeable_proxy",
            "source_verified", "dangerous_functions", "lp_lock",
            "contract_age", "holder_concentration"} <= names
    for c in report["checks"]:
        assert isinstance(c["evidence"], dict) and c["evidence"]
    hp = next(c for c in report["checks"] if c["name"] == "honeypot")
    assert hp["status"] == "pass" and hp["evidence"]["sellable"] is True
    assert report["verdict"] in ("OK", "WARN")
    assert not report["hard_fails"]

    result = agent.report(agent.decide(obs), agent.act(agent.decide(obs), None))
    assert result.metric == "wall_seconds" and result.value > 0
    assert result.outputs["report"]["target"] == to_checksum_address(CAKE) or \
           result.outputs["report"]["target"] == CAKE


@pytest.mark.live
def test_full_report_flags_deployed_honeypot_critical(hpt_artifact):
    with anvil_fork() as w3:
        deployer = w3.eth.accounts[0]
        wbnb = to_checksum_address(reference.token_address("WBNB"))
        router_addr = to_checksum_address(reference.contract("pancakeV2Router"))
        factory_addr = to_checksum_address(reference.contract("pancakeV2Factory"))
        liq_abi = hpt_artifact["abi"] + [
            {"name": "addLiquidityETH", "type": "function", "stateMutability": "payable",
             "inputs": [{"type": "address"}, {"type": "uint256"}, {"type": "uint256"},
                        {"type": "uint256"}, {"type": "address"}, {"type": "uint256"}],
             "outputs": [{"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}]},
        ]

        Hpt = w3.eth.contract(abi=hpt_artifact["abi"], bytecode=hpt_artifact["bytecode"]["object"])
        rcpt = w3.eth.wait_for_transaction_receipt(Hpt.constructor(10**24).transact({"from": deployer}))
        hpt_addr = rcpt["contractAddress"]
        hpt = w3.eth.contract(address=hpt_addr, abi=hpt_artifact["abi"])
        router = w3.eth.contract(address=router_addr, abi=liq_abi)

        w3.eth.wait_for_transaction_receipt(
            hpt.functions.approve(router_addr, _MAXU).transact({"from": deployer}))
        w3.eth.wait_for_transaction_receipt(
            router.functions.addLiquidityETH(
                hpt_addr, 500_000 * 10**18, 0, 0, deployer, int(time.time()) + 1800
            ).transact({"from": deployer, "value": w3.to_wei(10, "ether")}))
        factory = w3.eth.contract(address=factory_addr, abi=[
            {"name": "getPair", "type": "function", "stateMutability": "view",
             "inputs": [{"type": "address"}, {"type": "address"}], "outputs": [{"type": "address"}]}])
        pair = factory.functions.getPair(hpt_addr, wbnb).call()
        w3.eth.wait_for_transaction_receipt(
            hpt.functions.setPair(pair).transact({"from": deployer}))

        checks = gather(hpt_addr, w3, fetch_source=False)

    data = {"target": hpt_addr, "checks": [c.as_dict() for c in checks]}
    obs = Observation(data=data, snapshot_hash=canonical_hash(data))
    report = BscSentryAgent().decide(obs).params["report"]

    assert report["verdict"] == "CRITICAL"
    assert "honeypot" in report["hard_fails"]
    hp = next(c for c in report["checks"] if c["name"] == "honeypot")
    assert hp["hard_fail"] is True and hp["evidence"]["sellable"] is False
    assert hp["evidence"]["sell_revert"]  # the actual revert string is the evidence
