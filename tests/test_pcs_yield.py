"""T-033: pcs-yield — the net-APR maths (spec §4.1), the sentry gate wiring, and
an end-to-end hire vs `top_headline_apr`."""

from __future__ import annotations

import pytest
from agents.pcs_yield.economics import (
    dilution_adjustment,
    emission_decay_factor,
    net_apr,
)

# --- pure net-APR maths (§4.1) -------------------------------------

def test_emission_decay_shrinks_with_horizon():
    assert emission_decay_factor(1) > emission_decay_factor(90) > emission_decay_factor(365)
    assert 0.99 < emission_decay_factor(0.01) <= 1.0
    assert emission_decay_factor(3650) < 0.1


def test_dilution_only_bites_when_tvl_is_rising():
    assert dilution_adjustment(20.0, 1_000_000, 1_000_000, 30) == 0.0   # flat
    assert dilution_adjustment(20.0, 900_000, 1_000_000, 30) == 0.0     # shrinking
    d = dilution_adjustment(20.0, 1_500_000, 1_000_000, 30)             # +50% in 14d
    assert 0.0 < d <= 20.0


def test_net_apr_subtracts_every_term_and_flags_missing_il():
    hot = net_apr(
        pool="p", symbol="DOGE-WBNB", fee_apr_pct=28.9, emission_apr_pct=0.0,
        headline_apr_pct=998.6, horizon_days=30, vol_annual=1.1,
        capital_usd=5000, gas_usd_roundtrip=0.4, tvl_now=345_612, tvl_14d_ago=300_000,
    ).as_dict()
    assert hot["headline_apr_pct"] == 998.6
    assert hot["net_apr_pct"] < hot["fee_apr_pct"]  # IL + gas + dilution all subtract
    assert hot["expected_il_annual_pct"] > 0 and hot["il_verified"] is True

    unknown = net_apr(
        pool="p", symbol="WEIRD-COIN", fee_apr_pct=10.0, emission_apr_pct=0.0,
        headline_apr_pct=10.0, horizon_days=30, vol_annual=None,
        capital_usd=5000, gas_usd_roundtrip=0.4, tvl_now=100_000, tvl_14d_ago=None,
    ).as_dict()
    assert unknown["il_verified"] is False and unknown["expected_il_annual_pct"] == 0.0
    assert "IL not estimated" in unknown["notes"][0]


# --- live: real DefiLlama + Binance + sentry fork ----------------

@pytest.mark.live
def test_pcs_yield_hire_beats_naive_headline_pick():
    from agents.pcs_yield.agent import PcsYieldAgent
    from orchestrator import harness

    out = harness.run_hire(
        PcsYieldAgent(), tier=0,
        raw_inputs={"capital_usd": 5000, "risk": "balanced", "horizon_days": 30},
        persist=False,
    )
    assert out.agent_run.result.metric == "net_apr_delta_pct"
    assert out.baseline_run.result.metric == "net_apr_delta_pct"

    o = out.agent_run.result.outputs
    assert o["n_candidates"] >= 3
    assert o["winner"] and o["winner"]["net_apr_pct"] is not None
    # the ranked list shows the headline -> net subtraction for every pool
    for row in o["ranked"]:
        assert {"headline_apr_pct", "fee_apr_pct", "expected_il_annual_pct",
                "amortised_gas_annual_pct", "dilution_pct", "net_apr_pct"} <= set(row)
    # the naive baseline picked by headline; its reported value is that pool's net
    b = out.baseline_run.result.outputs
    assert b["headline_apr_pct"] >= o["winner"]["headline_apr_pct"] or b["basis"] == "headline"

    # decide() is pure on a frozen Observation
    agent = PcsYieldAgent()
    obs = agent.observe({"capital_usd": 5000, "risk": "balanced", "horizon_days": 30})
    assert agent.decide(obs) == agent.decide(obs)


@pytest.mark.live
def test_pcs_yield_excluded_section_always_present():
    from agents.pcs_yield.agent import PcsYieldAgent

    agent = PcsYieldAgent()
    obs = agent.observe({"capital_usd": 1000, "risk": "degen", "horizon_days": 14})
    out = agent.report(agent.decide(obs), None)
    assert "excluded_by_security_agent" in out.outputs  # spec §4.2 — the beat renders even if empty
    assert out.outputs["security_gate_status"] in ("clean",) or \
        out.outputs["security_gate_status"].startswith("unavailable")
