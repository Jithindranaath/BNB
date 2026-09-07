"""EchoAgent — the smallest possible concrete Agent.

No network, no data deps, no signing. `decide()` is a pure structural transform
of the Observation, so it is deterministic (the harness purity test relies on
this — spec.md §11.3). Used by T-022+ to exercise the harness and receipts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from agents.base import Actions, Agent, Decision, ExecContext, Observation, Result
from agents.manifest import Manifest

_MF = Manifest.model_validate(
    yaml.safe_load((Path(__file__).parent / "manifest.yaml").read_text())
)


def _snapshot_hash(data: dict) -> str:
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class EchoAgent(Agent):
    manifest = _MF

    def observe(self, inputs: dict) -> Observation:
        data = {"inputs": dict(inputs)}
        return Observation(data=data, snapshot_hash=_snapshot_hash(data))

    def decide(self, obs: Observation) -> Decision:
        n = float(obs.data["inputs"].get("n", 0))
        return Decision(kind="echo", params={"n": n}, rationale=f"echoing n={n}")

    def act(self, d: Decision, ctx: ExecContext) -> Actions:
        # Tier 0: never signs, never touches the chain.
        return Actions()

    def report(self, d: Decision, a: Actions) -> Result:
        return Result(
            metric=self.manifest.advantage_metric.name,
            unit=self.manifest.advantage_metric.unit,
            value=float(d.params["n"]),
            outputs={"echoed": d.params},
        )
