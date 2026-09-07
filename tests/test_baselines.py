"""T-023: each baseline runs against a fixed Observation and returns a Result in
the agent's declared metric/unit."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from agents.base import Observation
from orchestrator import baselines, registry

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "klines_bnbusdt_1h.csv"


def _klines() -> list[dict]:
    with FIXT.open() as f:
        return list(csv.DictReader(f))


def _obs(**data) -> Observation:
    return Observation(data=data, snapshot_hash="test")


def _manifest(agent_id: str):
    return registry.get(agent_id).manifest


def test_zero_baseline():
    r = baselines.run_baseline("zero", _obs(), _manifest("bnb-grid"))
    assert (r.metric, r.unit, r.value) == ("net_pnl_usd", "USD", 0.0)


@pytest.mark.live  # gas_cost_usd("swap_v2") -> live gas price + BNB spot
def test_hodl_baseline():
    m = _manifest("bnb-grid")
    obs = _obs(klines=_klines(), inputs={"capital_usd": 1000})
    r = baselines.run_baseline("hodl", obs, m)
    assert r.metric == "net_pnl_usd" and r.unit == "USD"
    p0 = float(_klines()[0]["open"])
    p1 = float(_klines()[-1]["close"])
    expected_gross = 1000 / p0 * p1 - 1000
    assert abs(r.value - (expected_gross - r.outputs["gas_usd"])) < 1e-6


def test_static_range_baseline_fees_minus_il_minus_gas():
    m = _manifest("pcs-rebalancer")
    pdd = [{"feesUSD": 500, "tvlUSD": 1_000_000} for _ in range(30)]
    obs = _obs(pool_day_datas=pdd, vol_annual=0.6, inputs={"capital_usd": 10_000},
              horizon_days=30)
    r = baselines.run_baseline("static_range", obs, m)
    assert r.metric == "net_fees_usd" and r.unit == "USD"
    assert r.outputs["fees_usd"] > 0 and r.outputs["il_usd"] > 0
    assert r.outputs["gas_usd"] > 0  # v3 mint+burn gas measured in T-043
    assert r.value == pytest.approx(
        r.outputs["fees_usd"] - r.outputs["il_usd"] - r.outputs["gas_usd"]
    )


def test_static_range_baseline_accepts_fee_apr_shortcut():
    m = _manifest("pcs-rebalancer")
    obs = _obs(fee_apr=0.20, vol_annual=0.6, inputs={"capital_usd": 10_000}, horizon_days=7)
    r = baselines.run_baseline("static_range", obs, m)
    assert r.outputs["fee_apr"] == 0.20 and r.outputs["fees_usd"] > 0


def test_top_headline_apr_baseline_reports_the_naive_picks_net_apr():
    m = _manifest("pcs-yield")
    # the naive picker chases apy=240 (pool b), but b's realistic net is 31%
    obs = _obs(pools=[
        {"pool": "a", "apy": 12.0, "net_apr_pct": 11.5},
        {"pool": "b", "apy": 240.0, "net_apr_pct": 31.0},
        {"pool": "c", "apy": 31.0, "net_apr_pct": 28.0},
    ])
    r = baselines.run_baseline("top_headline_apr", obs, m)
    assert r.metric == "net_apr_delta_pct" and r.value == 31.0
    assert r.outputs["top_pool"] == "b" and r.outputs["headline_apr_pct"] == 240.0


def test_top_headline_apr_baseline_falls_back_to_headline_without_net():
    m = _manifest("pcs-yield")
    obs = _obs(pools=[{"pool": "a", "apy": 12.0}, {"pool": "b", "apy": 240.0}])
    r = baselines.run_baseline("top_headline_apr", obs, m)
    assert r.value == 240.0 and r.outputs["basis"] == "headline"


def test_no_action_baseline_liquidation_and_safe():
    m = _manifest("venus-guard")
    safe = baselines.run_baseline("no_action", _obs(min_hf=1.4), m)
    assert safe.value == 0.0 and safe.outputs["liquidated"] is False

    liq = baselines.run_baseline(
        "no_action", _obs(min_hf=0.92, debt_usd=5000, liq_penalty_pct=0.1), m
    )
    assert liq.value == -500.0 and liq.outputs["liquidated"] is True
    assert m.advantage_metric.name == "usd_saved"


def test_manual_analyst_baseline_reads_fixture():
    m = _manifest("bsc-sentry")  # metric: wall_seconds
    obs = _obs(inputs={"target": "0x0000000000000000000000000000000000000000"})
    r = baselines.run_baseline("manual_analyst", obs, m)
    assert r.metric == "wall_seconds" and r.value == 420.0
    assert r.outputs["source"] == "manual_analyst"


def test_manual_analyst_missing_target_raises():
    m = _manifest("bsc-sentry")
    with pytest.raises(baselines.BaselineIncomplete):
        baselines.run_baseline(
            "manual_analyst", _obs(inputs={"target": "0xnot_in_fixture"}), m
        )


def test_unknown_baseline_id():
    with pytest.raises(KeyError):
        baselines.run_baseline("nope", _obs(), _manifest("bnb-grid"))
