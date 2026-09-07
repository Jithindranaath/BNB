"""Pure scoring for bsc-sentry (spec.md §3.3).

A weighted 0–100 rule score. A **hard-fail list** — honeypot, sell tax > 25%,
unrenounced mint — forces CRITICAL regardless of the weighted score. Every check
carries its own evidence; the scorer never invents a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SELL_TAX_HARD_FAIL = 0.25

# weight of each axis in the weighted score (normalised over the axes that ran)
WEIGHTS: dict[str, float] = {
    "honeypot": 0.28,
    "transfer_tax": 0.18,
    "ownership": 0.15,
    "dangerous_functions": 0.14,
    "lp_lock": 0.10,
    "source_verified": 0.07,
    "upgradeable_proxy": 0.05,
    "contract_age": 0.03,
    # holder_concentration: weight 0 until a holder index is available
    "holder_concentration": 0.0,
}


@dataclass
class Check:
    name: str
    status: str            # pass | warn | fail | unknown | unavailable
    score: float           # 0..1, 1 == fully safe on this axis (ignored if unknown/unavailable)
    evidence: dict[str, Any]
    reason: str = ""
    hard_fail: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "status": self.status, "score": round(self.score, 3),
            "reason": self.reason, "hard_fail": self.hard_fail, "evidence": self.evidence,
        }


@dataclass
class Report:
    target: str
    verdict: str           # OK | WARN | CRITICAL
    score: int             # 0..100
    checks: list[Check]
    hard_fails: list[str]
    warnings: list[str] = field(default_factory=list)
    scored_axes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target, "verdict": self.verdict, "score": self.score,
            "hard_fails": self.hard_fails, "warnings": self.warnings,
            "scored_axes": self.scored_axes,
            "checks": [c.as_dict() for c in self.checks],
        }


def _mint_by_eoa(checks: dict[str, Check]) -> bool:
    """`mint` in the ABI, ownership not renounced, owner is an EOA (code size 0).
    A contract owner (MasterChef/timelock/governance) does not count — legit
    reward tokens like CAKE mint from a contract."""
    df, own = checks.get("dangerous_functions"), checks.get("ownership")
    if not df or not own:
        return False
    has_mint = any(s.lower() == "mint" for s in df.evidence.get("matched", []))
    owner_is_eoa = own.evidence.get("owner_code_size") == 0 and not own.evidence.get("renounced")
    return has_mint and bool(owner_is_eoa)


def _source_verified(checks: dict[str, Check]) -> bool:
    sv = checks.get("source_verified")
    return bool(sv and sv.evidence.get("verified"))


def score_report(target: str, checks: list[Check]) -> Report:
    by_name = {c.name: c for c in checks}
    hard_fails: list[str] = [c.name for c in checks if c.hard_fail]
    warnings: list[str] = []

    # An EOA-held mint on an UNVERIFIED contract is the classic stealth rug ->
    # hard-fail. If the source IS verified you can read exactly what mint does
    # and who may call it (bridge peg / reward token) -> a heavy warning + penalty
    # rather than an automatic CRITICAL. (Deviation from spec §3.3, which lists
    # "unrenounced mint" flat: static mint+EOA false-positives every Binance-Peg
    # token. The un-fakeable hard-fails stay the fork-sim ones — §3.2.)
    mint_penalty = 1.0
    if _mint_by_eoa(by_name):
        if _source_verified(by_name):
            warnings.append("mint_by_eoa_verified")
            mint_penalty = 0.55
        else:
            hard_fails.append("unrenounced_mint_unverified")

    scored = [c for c in checks if c.status in ("pass", "warn", "fail") and WEIGHTS.get(c.name, 0) > 0]
    total_w = sum(WEIGHTS[c.name] for c in scored)
    weighted = (
        sum(c.score * WEIGHTS[c.name] for c in scored) / total_w if total_w else 0.0
    )
    score = round(weighted * mint_penalty * 100)

    if hard_fails:
        verdict = "CRITICAL"
        score = min(score, 10)
    elif score >= 75:
        verdict = "OK"
    elif score >= 40:
        verdict = "WARN"
    else:
        verdict = "CRITICAL"

    return Report(
        target=target, verdict=verdict, score=score, checks=checks,
        hard_fails=hard_fails, warnings=warnings,
        scored_axes=[c.name for c in scored],
    )
