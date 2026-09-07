"""Run harness: observe -> decide -> act -> report, then the receipt
(architecture.md §6).

  1. validate inputs against the manifest schema (per-field errors)
  2. observe()  -> Observation
  3. decide()   -> Decision           (PURE — enforced by the purity check)
  4. act()      -> Actions            (Tier 0/1 can't sign, by construction)
  5. report()   -> Result
  6. run the manifest's baseline on the SAME Observation
  7. write Receipt {agent result, baseline result, advantage delta, merkle leaf}

`data_snapshot_hash` = canonical_hash(Observation.data) — it is what makes a
receipt auditable: it proves the decision was made on the data we claim.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agents.base import (
    Actions,
    Agent,
    Decision,
    ExecContext,
    Observation,
    Result,
    TierViolation,
    canonical_hash,
)
from agents.manifest import Manifest
from sqlalchemy import text

from . import db
from .baselines import run_baseline


class InputValidationError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__(f"input validation failed: {errors}")
        self.errors = errors


@dataclass
class RunRecord:
    kind: str  # 'agent' | 'baseline'
    result: Result
    wall_seconds: float
    status: str = "ok"
    run_id: uuid.UUID | None = None
    error: str | None = None


@dataclass
class HireOutcome:
    agent_id: str
    tier: int
    task_hash: str
    data_snapshot_hash: str
    decision: Decision
    actions: Actions
    agent_run: RunRecord
    baseline_run: RunRecord
    delta: float
    favorable: bool
    merkle_leaf: str
    receipt_id: uuid.UUID | None = None
    persisted: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def agent_value(self) -> float:
        return self.agent_run.result.value

    @property
    def baseline_value(self) -> float:
        return self.baseline_run.result.value


def assert_pure(agent: Agent, obs: Observation) -> Decision:
    """decide() must be a pure function of the Observation (spec.md §11.3)."""
    d1 = agent.decide(obs)
    d2 = agent.decide(obs)
    if d1 != d2:
        raise AssertionError(f"{type(agent).__name__}.decide() is not pure: {d1!r} != {d2!r}")
    return d1


def _favorable(delta: float, manifest: Manifest) -> bool:
    if delta == 0:
        return False
    return delta > 0 if manifest.advantage_metric.higher_is_better else delta < 0


def run_hire(
    agent: Agent,
    tier: int,
    raw_inputs: dict[str, Any],
    *,
    signer: Any | None = None,
    persist: bool = True,
    on_phase: Callable[[str, str], None] | None = None,
) -> HireOutcome:
    manifest = agent.manifest
    emit = on_phase or (lambda *_: None)

    if tier not in manifest.tiers:
        raise ValueError(f"{manifest.id} does not offer tier {tier} (offers {manifest.tiers})")

    emit("validate", "checking inputs against the manifest")
    errors = manifest.validate_inputs(raw_inputs)
    if errors:
        raise InputValidationError(errors)
    inputs = manifest.apply_defaults(raw_inputs)

    task_hash = canonical_hash({"agent": manifest.id, "tier": tier, "inputs": inputs})
    ctx = ExecContext.for_tier(tier, signer=signer)

    # --- agent run -----------------------------------------------------
    emit("observe", "pulling data")
    t0 = time.monotonic()
    obs = agent.observe(inputs)
    snapshot_hash = canonical_hash(obs.data)

    emit("decide", "running the policy")
    decision = assert_pure(agent, obs)

    emit("act", f"tier {tier}")
    actions = agent.act(decision, ctx)
    if tier < 2 and (actions.tx_hashes or ctx.signer is not None):
        raise TierViolation(f"tier {tier} agent produced signed actions: {actions.tx_hashes}")

    emit("report", "assembling the result")
    agent_result = agent.report(decision, actions)
    agent_wall = time.monotonic() - t0
    agent_run = RunRecord("agent", agent_result, agent_wall)

    # --- baseline run (same Observation) -----------------------------
    emit("baseline", f"running {manifest.baseline}")
    b0 = time.monotonic()
    baseline_result = run_baseline(manifest.baseline, obs, manifest)
    baseline_run = RunRecord("baseline", baseline_result, time.monotonic() - b0)

    if baseline_result.unit != agent_result.unit or baseline_result.metric != agent_result.metric:
        raise ValueError(
            f"baseline metric/unit mismatch: agent {agent_result.metric}/{agent_result.unit} "
            f"vs baseline {baseline_result.metric}/{baseline_result.unit}"
        )

    delta = agent_result.value - baseline_result.value
    favorable = _favorable(delta, manifest)

    leaf = canonical_hash(
        {
            "agent": manifest.id,
            "tier": tier,
            "task_hash": task_hash,
            "data_snapshot_hash": snapshot_hash,
            "metric": agent_result.metric,
            "unit": agent_result.unit,
            "agent_value": agent_result.value,
            "baseline_value": baseline_result.value,
            "delta": delta,
        }
    )

    outcome = HireOutcome(
        agent_id=manifest.id,
        tier=tier,
        task_hash=task_hash,
        data_snapshot_hash=snapshot_hash,
        decision=decision,
        actions=actions,
        agent_run=agent_run,
        baseline_run=baseline_run,
        delta=delta,
        favorable=favorable,
        merkle_leaf=leaf,
    )

    if persist:
        emit("persist", "writing runs + receipt")
        _persist(agent, tier, inputs, task_hash, snapshot_hash, obs, decision, actions, outcome)
        outcome.persisted = True

    emit("done", "ok")
    return outcome


def ensure_agent(manifest: Manifest) -> None:
    """Upsert the agent's manifest into `agents` so `runs.agent_id` FK holds."""
    with db.session() as s:
        s.execute(
            text(
                """
                INSERT INTO agents (id, category, manifest)
                VALUES (:id, :category, CAST(:manifest AS jsonb))
                ON CONFLICT (id) DO UPDATE SET
                    category = EXCLUDED.category, manifest = EXCLUDED.manifest
                """
            ),
            {
                "id": manifest.id,
                "category": manifest.category,
                "manifest": manifest.model_dump_json(),
            },
        )
        s.commit()


def _persist(
    agent: Agent,
    tier: int,
    inputs: dict,
    task_hash: str,
    snapshot_hash: str,
    obs: Observation,
    decision: Decision,
    actions: Actions,
    outcome: HireOutcome,
) -> None:
    ensure_agent(agent.manifest)
    pair_id = uuid.uuid4()
    now = datetime.now(tz=UTC)

    ins_run = text(
        """
        INSERT INTO runs (agent_id, kind, pair_run_id, tier, task_hash, status,
                          started_at, ended_at, wall_seconds, inputs, outputs,
                          data_snapshot_hash)
        VALUES (:agent_id, :kind, :pair_id, :tier, :task_hash, :status,
                :started_at, :ended_at, :wall, CAST(:inputs AS jsonb),
                CAST(:outputs AS jsonb), :snap)
        RETURNING id
        """
    )
    import json as _json

    with db.session() as s:
        agent_run_id = s.execute(
            ins_run,
            {
                "agent_id": agent.manifest.id, "kind": "agent", "pair_id": pair_id,
                "tier": tier, "task_hash": task_hash, "status": outcome.agent_run.status,
                "started_at": now, "ended_at": datetime.now(tz=UTC),
                "wall": outcome.agent_run.wall_seconds,
                "inputs": _json.dumps(inputs, default=str),
                "outputs": _json.dumps(
                    {"decision": decision.__dict__, "result": outcome.agent_run.result.__dict__,
                     "tx_hashes": actions.tx_hashes},
                    default=str,
                ),
                "snap": snapshot_hash,
            },
        ).scalar_one()

        baseline_run_id = s.execute(
            ins_run,
            {
                "agent_id": agent.manifest.id, "kind": "baseline", "pair_id": pair_id,
                "tier": tier, "task_hash": task_hash, "status": outcome.baseline_run.status,
                "started_at": now, "ended_at": datetime.now(tz=UTC),
                "wall": outcome.baseline_run.wall_seconds,
                "inputs": _json.dumps(inputs, default=str),
                "outputs": _json.dumps(outcome.baseline_run.result.__dict__, default=str),
                "snap": snapshot_hash,
            },
        ).scalar_one()

        receipt_id = s.execute(
            text(
                """
                INSERT INTO receipts (agent_run_id, baseline_run_id, metric, unit,
                                      agent_value, baseline_value, delta, merkle_leaf)
                VALUES (:a, :b, :metric, :unit, :av, :bv, :delta, :leaf)
                RETURNING id
                """
            ),
            {
                "a": agent_run_id, "b": baseline_run_id,
                "metric": outcome.agent_run.result.metric,
                "unit": outcome.agent_run.result.unit,
                "av": outcome.agent_value, "bv": outcome.baseline_value,
                "delta": outcome.delta, "leaf": outcome.merkle_leaf,
            },
        ).scalar_one()
        s.commit()

    outcome.agent_run.run_id = agent_run_id
    outcome.baseline_run.run_id = baseline_run_id
    outcome.receipt_id = receipt_id
