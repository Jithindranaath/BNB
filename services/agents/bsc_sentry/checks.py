"""Individual bsc-sentry checks (spec.md §3.1). Every check returns a
`scoring.Check` carrying the evidence that produced it — never a bare score.
Checks degrade to status "unknown"/"unavailable" instead of raising.
"""

from __future__ import annotations

import time

from data import reference
from eth_utils import to_checksum_address
from web3 import Web3

from .fork import ForkSimResult
from .scoring import SELL_TAX_HARD_FAIL, Check

DEAD_ADDRS = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
}

# EIP-1967 storage slots
SLOT_IMPL = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
SLOT_ADMIN = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
SLOT_BEACON = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"

DANGEROUS_PATTERNS = (
    "mint", "blacklist", "setfee", "setfees", "settax", "settaxes", "updatefee",
    "updatefees", "setmaxtx", "setmaxwallet", "setmaxwalletsize", "pause",
    "enabletrading", "settradingenabled", "excludefromfee", "rescue",
    "withdrawstuck", "clearstuck", "setrouter", "updaterouter", "ownerwithdraw",
    "setswapenabled", "removelimits",
)


def _addr_from_slot(raw: bytes) -> str:
    return to_checksum_address("0x" + raw.hex()[-40:])


# --- fork-sim derived -------------------------------------------------

def checks_from_sim(sim: ForkSimResult) -> list[Check]:
    ev = sim.evidence()
    out: list[Check] = []

    if not sim.pair_found:
        out.append(Check("honeypot", "unknown", 0.0, ev,
                         "no v2 pair with WBNB — could not simulate a trade"))
        out.append(Check("transfer_tax", "unknown", 0.0, ev, "no trade to measure tax"))
        return out

    if sim.buyable and sim.sellable is False:
        out.append(Check("honeypot", "fail", 0.0, ev,
                         "bought fine but the sell transaction reverted", hard_fail=True))
    elif sim.sellable:
        out.append(Check("honeypot", "pass", 1.0, ev, "bought and sold back successfully"))
    else:
        out.append(Check("honeypot", "warn", 0.3, ev, "could not complete a buy"))

    st = sim.sell_tax_pct or 0.0
    bt = sim.buy_tax_pct or 0.0
    if st > SELL_TAX_HARD_FAIL:
        out.append(Check("transfer_tax", "fail", 0.0, ev,
                         f"sell tax {st:.0%} exceeds {SELL_TAX_HARD_FAIL:.0%}", hard_fail=True))
    elif max(st, bt) >= 0.10:
        out.append(Check("transfer_tax", "warn", 0.3, ev,
                         f"buy tax {bt:.1%}, sell tax {st:.1%}"))
    elif max(st, bt) >= 0.03:
        out.append(Check("transfer_tax", "warn", 0.7, ev,
                         f"buy tax {bt:.1%}, sell tax {st:.1%}"))
    else:
        out.append(Check("transfer_tax", "pass", 1.0, ev,
                         f"buy tax {bt:.1%}, sell tax {st:.1%}"))
    return out


# --- on-chain reads -------------------------------------------------

def check_ownership(target: str, w3: Web3) -> Check:
    target = to_checksum_address(target)
    owner = None
    for sig in ("owner()(address)", "getOwner()(address)"):
        try:
            fn = sig.split("(")[0]
            c = w3.eth.contract(address=target, abi=[
                {"name": fn, "type": "function", "stateMutability": "view",
                 "inputs": [], "outputs": [{"type": "address"}]}])
            owner = getattr(c.functions, fn)().call()
            break
        except Exception:  # noqa: BLE001, S112 - try the next owner getter
            continue
    if owner is None:
        return Check("ownership", "unknown", 0.0, {"owner": None},
                     "no owner()/getOwner() — may be ownerless or non-standard")

    renounced = owner.lower() in DEAD_ADDRS
    code_size = 0 if renounced else len(w3.eth.get_code(to_checksum_address(owner)))
    ev = {"owner": owner, "renounced": renounced, "owner_code_size": code_size}
    if renounced:
        return Check("ownership", "pass", 1.0, ev, "ownership renounced")
    if code_size == 0:
        return Check("ownership", "warn", 0.4, ev,
                     "owner is an EOA — one key can change token behaviour")
    return Check("ownership", "warn", 0.7, ev,
                 "owner is a contract (could be a timelock/multisig — unverified here)")


def check_upgradeable_proxy(target: str, w3: Web3) -> Check:
    target = to_checksum_address(target)
    impl = _addr_from_slot(w3.eth.get_storage_at(target, SLOT_IMPL))
    admin = _addr_from_slot(w3.eth.get_storage_at(target, SLOT_ADMIN))
    beacon = _addr_from_slot(w3.eth.get_storage_at(target, SLOT_BEACON))
    ev = {"impl_slot": impl, "admin_slot": admin, "beacon_slot": beacon}
    upgradeable = int(impl, 16) != 0 or int(beacon, 16) != 0
    if upgradeable:
        return Check("upgradeable_proxy", "warn", 0.3, ev,
                     "EIP-1967 proxy — the logic contract can be swapped")
    return Check("upgradeable_proxy", "pass", 1.0, ev, "not an EIP-1967 proxy")


def check_source_verified(source) -> Check:
    if source is None:
        return Check("source_verified", "warn", 0.3, {"verified": False},
                     "BscScan has no verified source for this address")
    ev = {"verified": source.verified, "contract_name": source.contract_name,
          "compiler": source.compiler_version, "proxy": source.proxy}
    if source.verified:
        return Check("source_verified", "pass", 1.0, ev, f"verified: {source.contract_name}")
    return Check("source_verified", "warn", 0.3, ev, "source not verified on BscScan")


def check_dangerous_functions(source) -> Check:
    if source is None or not source.verified or not source.abi:
        return Check("dangerous_functions", "unknown", 0.0, {"matched": []},
                     "source not verified — cannot scan the ABI")
    fns = [e.get("name", "") for e in source.abi if e.get("type") == "function"]
    matched = sorted({
        fn for fn in fns
        if any(p in fn.lower() for p in DANGEROUS_PATTERNS)
    })
    ev = {"matched": matched, "n_functions": len(fns)}
    if not matched:
        return Check("dangerous_functions", "pass", 1.0, ev, "no obviously dangerous functions")
    if len(matched) <= 2:
        return Check("dangerous_functions", "warn", 0.6, ev, f"owner powers: {matched}")
    return Check("dangerous_functions", "warn", 0.25, ev, f"many owner powers: {matched}")


def check_lp_lock(target: str, w3: Web3) -> Check:
    target = to_checksum_address(target)
    wbnb = to_checksum_address(reference.token_address("WBNB"))
    factory = w3.eth.contract(
        address=to_checksum_address(reference.contract("pancakeV2Factory")),
        abi=[{"name": "getPair", "type": "function", "stateMutability": "view",
              "inputs": [{"type": "address"}, {"type": "address"}], "outputs": [{"type": "address"}]}],
    )
    pair = factory.functions.getPair(target, wbnb).call()
    if int(pair, 16) == 0:
        return Check("lp_lock", "unknown", 0.0, {"pair": None}, "no v2 pair with WBNB")
    erc20 = w3.eth.contract(address=to_checksum_address(pair), abi=reference.abi("erc20"))
    supply = erc20.functions.totalSupply().call()
    burned = sum(
        erc20.functions.balanceOf(to_checksum_address(a)).call() for a in DEAD_ADDRS
    )
    burned_pct = burned / supply if supply else 0.0
    ev = {"pair": pair, "lp_total_supply": str(supply), "lp_burned_pct": round(burned_pct, 4),
          "note": "locker-contract detection (PinkLock/Unicrypt/Team.Finance) needs their "
                  "addresses in reference/ — added in T-032+; only burned LP is checked here"}
    if burned_pct >= 0.9:
        return Check("lp_lock", "pass", 1.0, ev, f"{burned_pct:.0%} of LP is burned")
    if burned_pct >= 0.5:
        return Check("lp_lock", "warn", 0.6, ev, f"{burned_pct:.0%} of LP is burned")
    return Check("lp_lock", "warn", 0.3, ev,
                 f"only {burned_pct:.0%} of LP burned and no known locker checked")


def check_contract_age(target: str, w3: Web3) -> Check:
    """Creation block by bisection on eth_getCode (BscScan's getcontractcreation
    is not on the free tier — T-003 finding)."""
    target = to_checksum_address(target)
    head = w3.eth.block_number
    if not w3.eth.get_code(target, block_identifier=head):
        return Check("contract_age", "unknown", 0.0, {"has_code": False}, "no bytecode at head")

    # probe: can this RPC answer historical getCode at all?
    probe_block = max(1, head - 5_000_000)
    try:
        probe_has = bool(w3.eth.get_code(target, block_identifier=probe_block))
    except Exception as e:  # noqa: BLE001
        return Check("contract_age", "unknown", 0.0,
                     {"error": str(e)[:160], "probe_block": probe_block},
                     "fork RPC won't serve historical state — needs an archive node")
    if probe_has:  # already existed 5M blocks ago -> comfortably old, skip the bisect
        age_days = (head - probe_block) * 3 / 86400
        return Check("contract_age", "pass", 1.0,
                     {"older_than_block": probe_block, "age_days_min": round(age_days),
                      "method": "eth_getCode probe"},
                     f"older than ~{age_days:.0f} days")

    lo, hi = probe_block, head
    for _ in range(40):
        if lo >= hi:
            break
        mid = (lo + hi) // 2
        try:
            has = bool(w3.eth.get_code(target, block_identifier=mid))
        except Exception:  # noqa: BLE001 - archive gap; treat as "not yet"
            has = False
        if has:
            hi = mid
        else:
            lo = mid + 1
    creation_block = lo
    age_blocks = head - creation_block
    age_days = age_blocks * 3 / 86400  # BSC ~3s blocks
    ev = {"creation_block": creation_block, "head_block": head,
          "age_blocks": age_blocks, "age_days_approx": round(age_days, 1),
          "method": "eth_getCode bisection"}
    if age_days >= 90:
        return Check("contract_age", "pass", 1.0, ev, f"~{age_days:.0f} days old")
    if age_days >= 30:
        return Check("contract_age", "pass", 0.8, ev, f"~{age_days:.0f} days old")
    if age_days >= 7:
        return Check("contract_age", "warn", 0.5, ev, f"only ~{age_days:.0f} days old")
    return Check("contract_age", "warn", 0.2, ev, f"brand new — ~{age_days:.1f} days old")


def check_holder_concentration() -> Check:
    return Check(
        "holder_concentration", "unavailable", 0.0,
        {"note": "top-holder share needs a holder index (BscScan PRO or a Transfer-event "
                 "scan). Not run; weighted 0 in scoring until available."},
        "no free holder index",
    )


def run_checks(target: str, w3: Web3, sim: ForkSimResult, *, source=None) -> list[Check]:
    checks: list[Check] = list(checks_from_sim(sim))
    for fn in (
        lambda: check_ownership(target, w3),
        lambda: check_upgradeable_proxy(target, w3),
        lambda: check_source_verified(source),
        lambda: check_dangerous_functions(source),
        lambda: check_lp_lock(target, w3),
        lambda: check_contract_age(target, w3),
        check_holder_concentration,
    ):
        try:
            checks.append(fn())
        except Exception as e:  # noqa: BLE001 - a broken check must not sink the report
            checks.append(Check(getattr(fn, "__name__", "check"), "unknown", 0.0,
                                {"error": str(e)[:200]}, "check raised"))
    return checks


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
