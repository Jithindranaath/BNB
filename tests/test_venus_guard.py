"""T-044: venus-guard — real on-chain HF, the vol-scaled trigger (§7.2), the
no_action liquidation replay (§7.4), and an end-to-end hire vs `no_action`.
"""

from __future__ import annotations

import pytest
from agents.venus_guard.health import vol_scaled_trigger
from agents.venus_guard.replay import Position, replay_guarded, replay_no_action
from orchestrator import db, harness
from sqlalchemy import text

# A real BSC Venus borrower (found via vUSDT RepayBorrow events): ETH/BTC/BNB
# collateral, ~$3.1k USDT borrow, HF ~1.3.
REAL_ACCOUNT = "0x222170d4eb3987506a0453ea21e83274743eca14"


# --- vol-scaled trigger (§7.2) ----------------------------------

def test_vol_scaled_trigger_scales_with_vol_and_z():
    calm = vol_scaled_trigger(0.30)
    wild = vol_scaled_trigger(0.90)
    assert 1.0 < calm < wild
    assert vol_scaled_trigger(0.6, z=4) > vol_scaled_trigger(0.6, z=2)


# --- no_action replay (§7.4) --------------------------------

def _pos(borrow=3000.0, volatile_adj=4000.0, stable_adj=150.0):
    return Position(borrow_usd=borrow, volatile_collateral_adj_usd=volatile_adj,
                    stable_collateral_adj_usd=stable_adj, close_factor=0.5,
                    liquidation_incentive=1.10)


def test_no_action_replay_reproduces_a_liquidation():
    pos = _pos()
    # k_liq = (3000 - 150) / 4000 = 0.7125 -> a decline to 0.65 crosses it
    path = [1.0, 0.95, 0.88, 0.80, 0.70, 0.65, 0.72]
    r = replay_no_action(pos, path)
    assert r.liquidated is True
    assert r.liq_step == 4 and r.liq_price_ratio == 0.70
    # penalty = close_factor * borrow * (incentive - 1) = 0.5 * 3000 * 0.10
    assert r.liquidation_loss_usd == pytest.approx(150.0)
    assert r.min_hf < 1.0


def test_no_action_replay_survives_a_mild_dip():
    r = replay_no_action(_pos(), [1.0, 0.97, 0.95, 0.98, 1.02])
    assert r.liquidated is False and r.liquidation_loss_usd == 0.0
    assert r.min_hf > 1.0


def test_guarded_replay_prevents_the_liquidation_and_saves_usd():
    pos = _pos()
    path = [1.0, 0.95, 0.88, 0.80, 0.70, 0.65, 0.72]
    g = replay_guarded(pos, path, trigger_hf=1.15, recovery_hf=1.25,
                       buffer_usd=2000.0, gas_usd_per_repay=0.05)
    assert g.n_repays > 0
    assert g.liquidated is False
    assert g.penalty_avoided_usd == pytest.approx(150.0)
    assert g.usd_saved == pytest.approx(150.0 - g.gas_usd)


def test_guarded_replay_with_a_tiny_buffer_still_gets_liquidated():
    pos = _pos()
    path = [1.0, 0.9, 0.75, 0.6, 0.5]
    g = replay_guarded(pos, path, trigger_hf=1.15, recovery_hf=1.25,
                       buffer_usd=50.0, gas_usd_per_repay=0.05)
    assert g.liquidated is True
    assert g.usd_saved <= 0  # spent gas, still liquidated


# --- live: real account -------------------------------------

@pytest.mark.live
def test_account_health_matches_the_comptroller():
    from data.sources import venus
    h = venus.account_health(REAL_ACCOUNT)
    assert h.total_borrow_usd > 100
    assert h.health_factor > 1.0
    # collateral_adjusted - borrow must equal the Comptroller's own liquidity number
    assert (h.collateral_adjusted_usd - h.total_borrow_usd) == pytest.approx(
        h.liquidity_usd - h.shortfall_usd, rel=1e-3
    )


@pytest.mark.live
def test_real_account_liquidates_under_a_severe_decline():
    from data.sources import venus
    h = venus.account_health(REAL_ACCOUNT)
    volatile = sum(m.collateral_adjusted_usd for m in h.markets
                   if not m.symbol.startswith(("vUSD", "vBUSD", "vDAI")) and m.supply_usd > 0)
    stable = h.collateral_adjusted_usd - volatile
    pos = Position(borrow_usd=h.total_borrow_usd, volatile_collateral_adj_usd=volatile,
                   stable_collateral_adj_usd=stable, close_factor=0.5, liquidation_incentive=1.10)
    # a real-magnitude crash (BTC/ETH have done -45% in a quarter more than once)
    r = replay_no_action(pos, [1.0, 0.9, 0.8, 0.7, 0.6, 0.55])
    assert r.liquidated is True and r.liquidation_loss_usd > 0


@pytest.fixture
def _clean_vg():
    def _wipe():
        with db.session() as s:
            s.execute(text("DELETE FROM receipts WHERE agent_run_id IN "
                           "(SELECT id FROM runs WHERE agent_id='venus-guard')"))
            s.execute(text("DELETE FROM runs WHERE agent_id='venus-guard'"))
            s.execute(text("DELETE FROM agent_stats WHERE agent_id='venus-guard'"))
            s.commit()
    _wipe(); yield; _wipe()


@pytest.mark.live
def test_venus_guard_hire_vs_no_action(_clean_vg):
    from agents.venus_guard.agent import NotAtRisk, VenusGuardAgent
    try:
        agent = VenusGuardAgent()
        out = harness.run_hire(
            agent, tier=1,
            raw_inputs={"account": REAL_ACCOUNT, "trigger_hf": 1.1,
                        "buffer_token": "USDT", "buffer_amount": 3000},
        )
    except NotAtRisk as e:
        pytest.skip(f"account no longer at risk: {e}")

    assert out.persisted and out.receipt_id
    assert out.agent_run.result.metric == "usd_saved"
    assert out.baseline_run.result.metric == "usd_saved"
    o = out.agent_run.result.outputs
    assert o["alert"] and "HF" in o["alert"]
    assert "no_action" in o and "guarded" in o
    assert o["trigger_hf"] >= 1.05

    # over a full year of real ETH price history the worst drawdown liquidates
    # this ~1.34 HF account; the guard's buffer repays should prevent it.
    if o["no_action"]["liquidated"]:
        assert o["no_action"]["liquidation_loss_usd"] > 0
        assert o["guarded"]["n_repays"] > 0
        assert out.delta > 0  # guard beats doing nothing
        assert "LIQUIDATED" in o["alert"]

    # decide() is pure on a frozen Observation (the harness also asserts this)
    obs = agent.observe({"account": REAL_ACCOUNT, "trigger_hf": 1.1,
                         "buffer_token": "USDT", "buffer_amount": 3000})
    assert agent.decide(obs) == agent.decide(obs)
