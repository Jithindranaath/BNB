"""bsc-sentry (security, Tier 0) — the judge's entry point.

observe(): fork BSC, buy/sell the target, read its storage + BscScan source
          (all I/O).
decide():  PURE — turn those observations into a weighted, evidence-backed score.
act():     nothing (Tier 0 can't sign).
report():  Result whose metric is `wall_seconds` (vs the manual_analyst baseline);
          the full security report rides in `outputs`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml
from data.sources import bscscan

from agents.base import Actions, Agent, Decision, ExecContext, Observation, Result, canonical_hash
from agents.manifest import Manifest

from .checks import now_iso, run_checks
from .fork import anvil_fork, simulate_trade
from .scoring import Check, score_report

_MF = Manifest.model_validate(
    yaml.safe_load((Path(__file__).parent / "manifest.yaml").read_text())
)


def gather(target: str, w3, *, fetch_source: bool = True) -> list[Check]:
    """Run the fork sim + on-chain + BscScan checks against an open fork `w3`."""
    sim = simulate_trade(target, w3)
    source = None
    if fetch_source:
        try:
            source = bscscan.get_contract_source(target)
        except Exception:  # noqa: BLE001 - unverified / no key / rate limit -> checks handle None
            source = None
    return run_checks(target, w3, sim, source=source)


class BscSentryAgent(Agent):
    manifest = _MF

    def __init__(self) -> None:
        self._t0 = 0.0

    def observe(self, inputs: dict) -> Observation:
        self._t0 = time.monotonic()
        target = str(inputs["target"])
        with anvil_fork() as w3:
            checks = gather(target, w3)
        data: dict[str, Any] = {
            "target": target,
            "generated_at": now_iso(),
            "checks": [c.as_dict() for c in checks],
        }
        return Observation(data=data, snapshot_hash=canonical_hash(data))

    def decide(self, obs: Observation) -> Decision:
        checks = [
            Check(
                name=c["name"], status=c["status"], score=float(c["score"]),
                evidence=c["evidence"], reason=c.get("reason", ""),
                hard_fail=bool(c["hard_fail"]),
            )
            for c in obs.data["checks"]
        ]
        report = score_report(obs.data["target"], checks)
        return Decision(
            kind="sentry_report",
            params={"report": report.as_dict()},
            rationale=f"{report.verdict} (score {report.score}/100)",
        )

    def act(self, d: Decision, ctx: ExecContext) -> Actions:
        return Actions()  # Tier 0 — never touches the chain

    def report(self, d: Decision, a: Actions) -> Result:
        wall = time.monotonic() - self._t0 if self._t0 else 0.0
        return Result(
            metric=self.manifest.advantage_metric.name,   # wall_seconds
            unit=self.manifest.advantage_metric.unit,
            value=wall,
            outputs={"report": d.params["report"]},
        )
