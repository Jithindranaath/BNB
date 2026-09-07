"""T-042: pcs-rebalancer range selection (§6.1), the cost-aware rebalance rule
(§6.2 — BOTH the rebalance and the decline-to-rebalance branches), the paper sim,
and an end-to-end paper hire -> receipt vs `static_range`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from agents.pcs_rebalancer.economics import rebalance_decision
from agents.pcs_rebalancer.range import FEE_TIER_SPACING, select_range
from agents.pcs_rebalancer.sim import simulate_rebalancer
from orchestrator import db, harness
from sqlalchemy import text

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "klines_bnbusdt_1h.csv"
# WBNB/USDT 0.05% v3 pool (from PancakeV3Factory.getPool, verified earlier)
POOL = "0x36696169C63e42cd08ce11f5deeBbCeBae652050"


@pytest.fixture(scope="module")
def klines() -> pd.DataFrame:
    df = pd.read_csv(FIXT, parse_dates=["open_time"])
    df["volume"] = 0.0
    return df


# --- range selection ------------------------------------------------

def test_select_range_snaps_and_scales_with_risk(klines):
    price = float(klines["close"].iloc[-1])
    tight = select_range(klines, price, "tight", fee_tier=500)
    bal = select_range(klines, price, "balanced", fee_tier=500)
    wide = select_range(klines, price, "wide", fee_tier=500)

    for r in (tight, bal, wide):
        assert r.tick_lower < r.tick_upper
        assert r.tick_lower % r.spacing == 0 and r.tick_upper % r.spacing == 0
        assert r.pa < price < r.pb
    assert tight.half_width_frac < bal.half_width_frac < wide.half_width_frac
    assert bal.spacing == FEE_TIER_SPACING[500]


# --- the cost-aware rule: BOTH branches ---------------------------

def _decide(fee_apr_base: float, gas: float = 1.0):
    return rebalance_decision(
        capital_usd=5000, fee_apr_base=fee_apr_base, new_half_width_frac=0.08,
        vol_annual=0.55, horizon_days=7, elapsed_days=3, current_half_width_frac=0.08,
        gas_close_usd=gas, gas_open_usd=gas,
    )


def test_rebalance_branch_when_fees_beat_costs():
    d = _decide(fee_apr_base=0.60)  # rich pool
    assert d.act is True
    assert d.net_usd > 0
    assert d.reason.startswith("rebalance:")


def test_decline_to_rebalance_branch_shows_the_arithmetic():
    d = _decide(fee_apr_base=0.005, gas=3.0)  # thin pool, pricier gas
    assert d.act is False
    assert "not economic" in d.reason
    assert "vs $" in d.reason and "expected fees" in d.reason
    assert d.expected_fees_usd < d.realised_il_usd + d.gas_cost_usd


# --- paper sim exercises both branches -------------------------

def test_sim_rebalances_in_a_rich_pool(klines):
    rng = select_range(klines, float(klines["close"].iloc[-1]), "balanced", fee_tier=500)
    r = simulate_rebalancer(klines, rng, capital_usd=5000, fee_apr_base=0.80,
                            gas_open_usd=0.2, gas_close_usd=0.5, checkpoint_hours=24)
    assert r.n_rebalances > 0
    assert r.decisions and all("reason" in d for d in r.decisions)


def test_sim_declines_to_rebalance_in_a_thin_pool(klines):
    rng = select_range(klines, float(klines["close"].iloc[-1]), "balanced", fee_tier=500)
    r = simulate_rebalancer(klines, rng, capital_usd=5000, fee_apr_base=0.002,
                            gas_open_usd=1.0, gas_close_usd=2.0, checkpoint_hours=24)
    assert r.n_holds > 0
    held = [d for d in r.decisions if d["act"] is False]
    assert held and all("not economic" in d["reason"] for d in held)


# --- end to end --------------------------------------------

@pytest.fixture
def _clean_reb():
    def _wipe():
        with db.session() as s:
            s.execute(text("DELETE FROM receipts WHERE agent_run_id IN "
                           "(SELECT id FROM runs WHERE agent_id='pcs-rebalancer')"))
            s.execute(text("DELETE FROM runs WHERE agent_id='pcs-rebalancer'"))
            s.execute(text("DELETE FROM agent_stats WHERE agent_id='pcs-rebalancer'"))
            s.commit()
    _wipe(); yield; _wipe()


@pytest.mark.live
def test_rebalancer_paper_hire_vs_static_range(_clean_reb):
    from agents.pcs_rebalancer.agent import PcsRebalancerAgent, UnsupportedPool
    try:
        agent = PcsRebalancerAgent(default_window_days=10)
        out = harness.run_hire(
            agent, tier=1,
            raw_inputs={"pool": POOL, "capital_usd": 5000, "risk": "balanced"},
        )
    except UnsupportedPool as e:
        pytest.skip(f"DefiLlama has no fee data for the pool: {e}")

    assert out.persisted and out.receipt_id
    assert out.agent_run.result.metric == "net_fees_usd"
    assert out.baseline_run.result.metric == "net_fees_usd"

    o = out.agent_run.result.outputs
    assert o["range"]["tick_lower"] < o["range"]["tick_upper"]
    assert {"n_rebalances", "n_holds", "window_days"} <= set(o["stats"])
    assert o["decisions"], "the decision log (incl. every hold, with arithmetic) must be present"


@pytest.mark.live
def test_rebalancer_decide_is_pure():
    from agents.pcs_rebalancer.agent import PcsRebalancerAgent, UnsupportedPool
    try:
        agent = PcsRebalancerAgent(default_window_days=7)
        obs = agent.observe({"pool": POOL, "capital_usd": 3000, "risk": "tight"})
    except UnsupportedPool as e:
        pytest.skip(str(e))
    assert agent.decide(obs) == agent.decide(obs)
