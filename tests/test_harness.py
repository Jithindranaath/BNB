"""T-022: the run harness produces a valid receipt with a baseline attached, and
decide() is proven pure. Persists to the docker postgres, so `-m live`.
"""

from __future__ import annotations

import pytest
from agents._echo.agent import EchoAgent
from agents.base import Observation, canonical_hash
from orchestrator import db, harness
from sqlalchemy import text

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def _clean_echo():
    def _wipe():
        with db.session() as s:
            s.execute(text(
                "DELETE FROM receipts WHERE agent_run_id IN "
                "(SELECT id FROM runs WHERE agent_id = '_echo')"
            ))
            s.execute(text("DELETE FROM runs WHERE agent_id = '_echo'"))
            s.execute(text("DELETE FROM agent_stats WHERE agent_id = '_echo'"))
            s.execute(text("DELETE FROM agents WHERE id = '_echo'"))
            s.commit()
    _wipe()
    yield
    _wipe()


def test_echo_hire_writes_receipt_with_baseline():
    out = harness.run_hire(EchoAgent(), tier=0, raw_inputs={"n": 42})

    assert out.persisted
    assert out.agent_value == 42.0
    assert out.baseline_value == 0.0            # `zero` baseline
    assert out.delta == 42.0
    assert out.favorable is True                # echo_value higher_is_better
    assert out.data_snapshot_hash == canonical_hash({"inputs": {"n": 42}})
    assert len(out.merkle_leaf) == 64

    with db.session() as s:
        row = s.execute(
            text(
                """
                SELECT r.metric, r.unit, r.agent_value, r.baseline_value, r.delta,
                       r.merkle_leaf,
                       ar.kind AS ar_kind, br.kind AS br_kind,
                       ar.data_snapshot_hash AS ar_snap, br.data_snapshot_hash AS br_snap,
                       ar.pair_run_id = br.pair_run_id AS paired
                FROM receipts r
                JOIN runs ar ON ar.id = r.agent_run_id
                JOIN runs br ON br.id = r.baseline_run_id
                WHERE r.id = :rid
                """
            ),
            {"rid": out.receipt_id},
        ).mappings().one()

    assert row["metric"] == "echo_value" and row["unit"] == "count"
    assert float(row["agent_value"]) == 42.0 and float(row["delta"]) == 42.0
    assert row["ar_kind"] == "agent" and row["br_kind"] == "baseline"
    assert row["ar_snap"] == row["br_snap"] == out.data_snapshot_hash
    assert row["paired"] is True
    assert row["merkle_leaf"] == out.merkle_leaf


def test_decide_is_pure_on_a_frozen_observation():
    agent = EchoAgent()
    obs = Observation(data={"inputs": {"n": 7}}, snapshot_hash="frozen")
    d = harness.assert_pure(agent, obs)   # raises if decide() is impure
    assert agent.decide(obs) == d
    assert agent.decide(obs) == agent.decide(obs)


def test_rejects_tier_the_agent_does_not_offer():
    with pytest.raises(ValueError):
        harness.run_hire(EchoAgent(), tier=2, raw_inputs={"n": 1}, persist=False)


def test_input_validation_error_is_per_field():
    with pytest.raises(harness.InputValidationError) as ei:
        harness.run_hire(EchoAgent(), tier=0, raw_inputs={}, persist=False)
    assert ei.value.errors.get("n") == "required"


def test_dry_run_does_not_persist():
    out = harness.run_hire(EchoAgent(), tier=0, raw_inputs={"n": 3}, persist=False)
    assert out.persisted is False and out.receipt_id is None
    assert out.delta == 3.0
