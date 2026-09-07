"""Agent ABC — every agent implements exactly this (architecture.md §8).

The shape here is fixed by architecture.md §8 and must not drift. The manifest
model lives in `agents.manifest`; the loader/registry in `agents.registry`.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .manifest import Manifest

__all__ = [
    "Actions",
    "Agent",
    "Decision",
    "ExecContext",
    "Manifest",
    "Observation",
    "Result",
    "TierViolation",
    "canonical_hash",
]


def canonical_hash(obj: Any) -> str:
    """sha256 of the canonicalised JSON of `obj`. The one hashing rule used for
    both `Observation.snapshot_hash` and the harness's `data_snapshot_hash` /
    `task_hash` / merkle leaf, so they always agree (architecture.md §6)."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class Observation:
    """Everything decide() is allowed to see. `snapshot_hash` is sha256 of the
    canonicalised JSON of `data` — it proves the decision was made on this data."""

    data: dict[str, Any]
    snapshot_hash: str


@dataclass(frozen=True)
class Decision:
    """Output of the pure policy. Same Observation -> identical Decision."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""


@dataclass
class Actions:
    """What act() did. Tier 0: always empty."""

    performed: list[dict[str, Any]] = field(default_factory=list)
    tx_hashes: list[str] = field(default_factory=list)


@dataclass
class Result:
    """Handed back to the harness, which turns it into a Receipt."""

    metric: str
    unit: str
    value: float
    outputs: dict[str, Any] = field(default_factory=dict)


class TierViolation(RuntimeError):
    """Raised if a Tier 0/1 context is asked to sign anything (spec.md §11.4)."""


@dataclass(frozen=True)
class ExecContext:
    """`tier` gates capability. For Tier 0 and 1, `signer` is None **by
    construction** — `for_tier()` drops any signer passed, and the dataclass is
    frozen so it can't be set later (architecture.md §10). Tier 2 requires a
    real signer at construction time.
    """

    tier: int
    signer: Any | None = None

    @classmethod
    def for_tier(cls, tier: int, signer: Any | None = None) -> ExecContext:
        if tier not in (0, 1, 2):
            raise ValueError(f"tier must be 0, 1 or 2 (got {tier})")
        if tier < 2:
            return cls(tier=tier, signer=None)  # signer dropped on purpose
        if signer is None:
            raise TierViolation("a Tier 2 context must be constructed with a signer")
        return cls(tier=tier, signer=signer)

    @property
    def can_sign(self) -> bool:
        return self.tier >= 2 and self.signer is not None

    def require_signer(self) -> Any:
        if not self.can_sign:
            raise TierViolation(f"tier {self.tier} context cannot sign")
        return self.signer


class Agent(ABC):
    """See architecture.md §8. Implemented per-agent from Phase 3 onward."""

    manifest: Manifest  # loaded + validated from manifest.yaml by agents.registry

    @abstractmethod
    def observe(self, inputs: dict) -> Observation:
        """Pull ALL data via packages/data. No network calls anywhere else."""

    @abstractmethod
    def decide(self, obs: Observation) -> Decision:
        """PURE. No I/O, no randomness, no clock reads."""

    @abstractmethod
    def act(self, d: Decision, ctx: ExecContext) -> Actions:
        """ctx.tier gates capability. ctx.signer is None for tier 0 and 1."""

    @abstractmethod
    def report(self, d: Decision, a: Actions) -> Result:
        ...
