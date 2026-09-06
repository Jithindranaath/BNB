"""T-001 scaffold smoke test. Proves the import roots and manifests are wired.

Real tests land per task (purity test T-022, tier test T-024, calibration T-012...).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ["pcs-rebalancer", "bnb-grid", "pcs-yield", "venus-guard", "bsc-sentry"]
AGENT_DIRS = {
    "pcs-rebalancer": "pcs_rebalancer",
    "bnb-grid": "bnb_grid",
    "pcs-yield": "pcs_yield",
    "venus-guard": "venus_guard",
    "bsc-sentry": "bsc_sentry",
}


def test_data_package_imports():
    import data  # noqa: F401
    from data import calibrate  # noqa: F401
    from data.sources import binance, bscscan, llama, rpc, subgraph, venus  # noqa: F401


def test_orchestrator_and_agent_base_import():
    from agents.base import Agent, ExecContext, TierViolation
    import pytest

    # Tier 0/1 contexts must refuse to sign (architecture.md §10; full test in T-024).
    ctx = ExecContext(tier=0)
    assert ctx.signer is None
    with pytest.raises(TierViolation):
        ctx.require_signer()

    assert hasattr(Agent, "observe") and hasattr(Agent, "decide")


def test_every_agent_has_a_valid_looking_manifest():
    for agent_id in AGENTS:
        p = ROOT / "services" / "agents" / AGENT_DIRS[agent_id] / "manifest.yaml"
        assert p.exists(), f"missing manifest for {agent_id}"
        m = yaml.safe_load(p.read_text())
        assert m["id"] == agent_id
        assert m["category"] in {
            "rebalancing",
            "grid",
            "yield",
            "health_factor",
            "security",
        }
        assert isinstance(m["tiers"], list) and m["tiers"]
        assert "baseline" in m and "advantage_metric" in m


def test_reference_files_exist_and_are_json():
    ref = ROOT / "packages" / "data" / "reference"
    for name in ("addresses.json", "tokens.json", "subgraphs.json"):
        json.loads((ref / name).read_text())
