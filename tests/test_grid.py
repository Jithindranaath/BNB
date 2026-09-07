"""T-040: bnb-grid calibration + paper simulation + circuit breaker, and an
end-to-end paper hire that produces a receipt vs `hodl` with the §5.5 stats.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from agents.bnb_grid.agent import BnbGridAgent
from agents.bnb_grid.grid import calibrate_grid
from agents.bnb_grid.sim import simulate
from orchestrator import db, harness
from sqlalchemy import text

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "klines_bnbusdt_1h.csv"


@pytest.fixture(scope="module")
def klines() -> pd.DataFrame:
    df = pd.read_csv(FIXT, parse_dates=["open_time"])
    df["volume"] = 0.0
    return df


# --- calibration -----------------------------------------------------

def test_calibrate_grid_shape(klines):
    g = calibrate_grid(klines, capital_usd=1200, user_levels=12, risk="balanced")
    assert g.levels == 12 and len(g.lines) == 12
    assert list(g.lines) == sorted(g.lines)
    assert g.lower < g.mid_price < g.upper
    assert g.size_usd_per_level == pytest.approx(1200 / 12)
    assert 0 < g.spacing_frac < 0.5
    assert g.atr > 0


def test_calibrate_clamps_levels(klines):
    assert calibrate_grid(klines, 1000, 2, "tight").levels == 5
    assert calibrate_grid(klines, 1000, 999, "wide").levels == 30
    assert calibrate_grid(klines, 1000, 20, "balanced").spacing_frac < \
           calibrate_grid(klines, 1000, 20, "wide").spacing_frac


# --- simulation ----------------------------------------------------

def test_simulate_is_deterministic_and_trades(klines):
    # calibrate on the full window, simulate on a sub-window (as the agent does:
    # calib_days=30 > default_window_days=7)
    g = calibrate_grid(klines, 2000, 15, "balanced")
    sim_window = klines.iloc[:240]
    a = simulate(sim_window, g, gas_usd_per_fill=0.05)
    b = simulate(sim_window, g, gas_usd_per_fill=0.05)
    assert (a.net_pnl_usd, a.n_trades, a.max_drawdown_pct) == \
           (b.net_pnl_usd, b.n_trades, b.max_drawdown_pct)
    assert a.n_trades > 0, "a 15-level grid over 10 days should fill something"
    assert len(a.equity_curve) > 0
    assert a.final_equity_usd == pytest.approx(2000 + a.net_pnl_usd)
    assert 0.0 <= a.win_rate <= 1.0
    assert a.max_drawdown_pct >= 0.0
    if a.halted:  # a trend can legitimately trip the breaker
        assert a.halt_reason


def _synthetic(prices: list[float]) -> list[dict]:
    return [
        {"open_time_ms": i * 3_600_000, "open": p, "high": p * 1.001,
         "low": p * 0.999, "close": p, "volume": 0.0}
        for i, p in enumerate(prices)
    ]


def test_circuit_breaker_halts_on_range_exit(klines):
    g = calibrate_grid(klines, 1000, 10, "balanced")
    # ramp far above the upper bound
    path = [g.mid_price] * 5 + [g.upper * 1.5] * 5
    r = simulate(_synthetic(path), g, gas_usd_per_fill=0.01)
    assert r.halted and "range" in (r.halt_reason or "")


def test_circuit_breaker_halts_on_max_loss(klines):
    g = calibrate_grid(klines, 1000, 12, "balanced")
    # drop hard: grid buys all the way down, inventory value craters
    path = [g.mid_price] + [g.lower * 0.5] * 8
    r = simulate(_synthetic(path), g, gas_usd_per_fill=0.01, max_loss_pct=5.0)
    assert r.halted


# --- end to end ---------------------------------------------------

@pytest.fixture
def _clean_grid():
    def _wipe():
        with db.session() as s:
            s.execute(text("DELETE FROM receipts WHERE agent_run_id IN "
                           "(SELECT id FROM runs WHERE agent_id='bnb-grid')"))
            s.execute(text("DELETE FROM runs WHERE agent_id='bnb-grid'"))
            s.execute(text("DELETE FROM agent_stats WHERE agent_id='bnb-grid'"))
            s.commit()
    _wipe(); yield; _wipe()


@pytest.mark.live
def test_grid_paper_hire_produces_receipt_vs_hodl(_clean_grid):
    agent = BnbGridAgent(default_window_days=10)
    out = harness.run_hire(
        agent, tier=1,
        raw_inputs={"pair": "BNB-USDT", "capital_usd": 1000, "grid_levels": 12, "risk": "balanced"},
    )
    assert out.persisted and out.receipt_id
    assert out.agent_run.result.metric == "net_pnl_usd"
    assert out.baseline_run.result.metric == "net_pnl_usd"  # hodl, same unit

    stats = out.agent_run.result.outputs["stats"]
    for k in ("win_rate", "n_trades", "window_days", "max_drawdown_pct", "capital_at_risk_usd"):
        assert k in stats
    assert stats["window_days"] > 5
    assert out.agent_run.result.outputs["grid"]["levels"] == 12


@pytest.mark.live
def test_grid_decide_is_pure():
    agent = BnbGridAgent(default_window_days=7)
    obs = agent.observe({"pair": "BNB-USDT", "capital_usd": 500, "grid_levels": 10, "risk": "tight"})
    assert agent.decide(obs) == agent.decide(obs)
