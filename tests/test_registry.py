"""T-020 acceptance: manifest schema, the loader, and a no-op EchoAgent."""

from __future__ import annotations

import textwrap

import pytest
from agents._echo.agent import EchoAgent
from agents.base import Agent, ExecContext
from agents.manifest import Manifest
from orchestrator import registry

REAL_AGENTS = {"pcs-rebalancer", "bnb-grid", "pcs-yield", "venus-guard", "bsc-sentry"}


def test_all_real_manifests_load_and_validate():
    reg = registry.load_registry()
    assert set(reg) == REAL_AGENTS
    for entry in reg.values():
        assert entry.available, f"{entry.id} unavailable: {entry.error}"
        assert isinstance(entry.manifest, Manifest)


def test_hidden_echo_agent_excluded_by_default():
    assert "_echo" not in registry.load_registry()
    assert "_echo" in registry.load_registry(include_hidden=True)


def test_invalid_manifest_makes_agent_unavailable_not_partial(tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    (good / "manifest.yaml").write_text(textwrap.dedent("""
        id: good-agent
        name: Good
        category: yield
        one_liner: fine
        tiers: [0]
        inputs: {}
        data_deps: []
        baseline: top_headline_apr
        advantage_metric: { name: x, unit: pct, higher_is_better: true }
        pricing: { model: free }
    """))
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.yaml").write_text("id: bad-agent\nname: Bad\ncategory: not_a_category\n")

    reg = registry.load_registry(tmp_path)
    assert reg["good-agent"].available and reg["good-agent"].manifest is not None
    assert not reg["bad-agent"].available
    assert reg["bad-agent"].manifest is None
    assert reg["bad-agent"].error and "invalid manifest" in reg["bad-agent"].error


def test_tier2_requires_kill_switch():
    base = {
        "id": "t2", "name": "T2", "category": "grid", "one_liner": "x", "tiers": [2],
        "inputs": {}, "data_deps": [], "baseline": "hodl",
        "advantage_metric": {"name": "p", "unit": "USD", "higher_is_better": True},
        "pricing": {"model": "free"},
    }
    with pytest.raises(ValueError, match="kill_switch"):
        Manifest.model_validate(base)
    Manifest.model_validate({**base, "kill_switch": {"max_loss_pct": 5}})  # ok


def test_validate_inputs_reports_per_field_errors():
    m = registry.get("pcs-rebalancer").manifest
    errs = m.validate_inputs({})
    assert errs.get("pool") == "required" and errs.get("capital_usd") == "required"

    errs = m.validate_inputs({"pool": "0x" + "a" * 40, "capital_usd": 10})
    assert "must be >= 50" in errs["capital_usd"]

    errs = m.validate_inputs({"pool": "0x" + "a" * 40, "capital_usd": 500, "risk": "wild"})
    assert "one of" in errs["risk"]

    assert m.validate_inputs({"pool": "0x" + "a" * 40, "capital_usd": 500}) == {}

    assert m.validate_inputs({"pool": "0x" + "a" * 40, "capital_usd": 500, "foo": 1}) == {
        "foo": "unknown input"
    }


def test_apply_defaults():
    m = registry.get("pcs-rebalancer").manifest
    assert m.apply_defaults({"pool": "0x0", "capital_usd": 100})["risk"] == "balanced"


def test_echo_agent_is_a_concrete_agent_and_runs():
    a = EchoAgent()
    assert isinstance(a, Agent)
    obs = a.observe({"n": 42})
    assert obs.snapshot_hash and len(obs.snapshot_hash) == 64
    d1 = a.decide(obs)
    d2 = a.decide(obs)
    assert d1 == d2  # pure (full purity test in T-022)
    result = a.report(d1, a.act(d1, ExecContext(tier=0)))
    assert result.metric == "echo_value" and result.value == 42.0
