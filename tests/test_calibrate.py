"""T-012 acceptance: each calibration fn checked against an independent
computation on a FROZEN REAL fixture (fixtures/klines_bnbusdt_1h.csv), plus
invariants. No synthetic price series (R3) — the fixture is real BNBUSDT 1h data.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from data import calibrate

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "klines_bnbusdt_1h.csv"


@pytest.fixture(scope="module")
def klines() -> pd.DataFrame:
    df = pd.read_csv(FIXT, parse_dates=["open_time"])
    assert len(df) > 300
    return df


# --- atr -----------------------------------------------------------------

def _ref_atr(df: pd.DataFrame, period: int) -> float:
    """Independent plain-Python Wilder ATR."""
    h = df["high"].tolist()
    low = df["low"].tolist()
    c = df["close"].tolist()
    tr = [
        max(h[i] - low[i], abs(h[i] - c[i - 1]), abs(low[i] - c[i - 1]))
        for i in range(1, len(c))
    ]
    atr = sum(tr[:period]) / period
    for t in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[t]) / period
    return atr


def test_atr_matches_reference(klines):
    got = calibrate.atr(klines, period=14)
    exp = _ref_atr(klines, 14)
    assert math.isclose(got, exp, rel_tol=1e-12)
    assert 0 < got < klines["close"].mean() * 0.1  # ATR is a few $, not hundreds


def test_atr_needs_enough_candles(klines):
    with pytest.raises(ValueError):
        calibrate.atr(klines.head(10), period=14)


# --- realized_vol ------------------------------------------------------

def test_realized_vol_matches_reference(klines):
    got = calibrate.realized_vol(klines, window_hours=720)
    close = klines["close"].to_numpy(float)
    lr = np.diff(np.log(close))
    exp = lr.std(ddof=1) * math.sqrt(24 * 365)
    assert math.isclose(got, exp, rel_tol=1e-12)
    assert 0.1 < got < 3.0  # annualised vol, plausible band for BNB


def test_realized_vol_windowing(klines):
    short = calibrate.realized_vol(klines, window_hours=48)
    full = calibrate.realized_vol(klines, window_hours=0)
    assert short > 0 and full > 0 and short != full


# --- fee_apr ---------------------------------------------------------

def test_fee_apr_hand_value():
    days = [
        {"feesUSD": 100, "tvlUSD": 10_000},
        {"feesUSD": 200, "tvlUSD": 10_000},
        {"feesUSD": 300, "tvlUSD": 10_000},
    ]
    # sum(fees)=600 / mean(tvl)=10000 * 365/3 = 7.3
    assert math.isclose(calibrate.fee_apr(days, days=30), 7.3, rel_tol=1e-12)


def test_fee_apr_accepts_snake_case_and_models():
    from datetime import UTC, datetime

    from data.sources.subgraph import PoolDayData

    rows = [
        PoolDayData(date=datetime(2026, 1, d, tzinfo=UTC), fees_usd=50, tvl_usd=5000, volume_usd=0)
        for d in (1, 2)
    ]
    # 100 / 5000 * 365/2 = 3.65
    assert math.isclose(calibrate.fee_apr(rows), 3.65, rel_tol=1e-12)


# --- il_estimate ---------------------------------------------------

def test_il_zero_when_no_risk():
    assert calibrate.il_estimate(vol_annual=0.0, horizon_days=30, range_width_pct=0.5) == 0.0
    assert calibrate.il_estimate(vol_annual=0.6, horizon_days=0, range_width_pct=0.5) == 0.0


def test_il_positive_and_wider_range_is_safer():
    narrow = calibrate.il_estimate(0.6, 30, 0.15)
    mid = calibrate.il_estimate(0.6, 30, 0.40)
    wide = calibrate.il_estimate(0.6, 30, 0.90)
    assert narrow > mid > wide > 0
    assert narrow < 0.5  # sane magnitude (fraction, not %)


def test_il_grows_with_vol_and_horizon():
    base = calibrate.il_estimate(0.4, 14, 0.5)
    more_vol = calibrate.il_estimate(0.9, 14, 0.5)
    more_time = calibrate.il_estimate(0.4, 90, 0.5)
    assert more_vol > base and more_time > base


# --- gas_cost_usd ------------------------------------------------

def test_gas_cost_usd_arithmetic():
    # 118387 units * 1 gwei * $600 / 1e18 = 0.0710322
    got = calibrate.gas_cost_usd("swap_v2", gas_price_wei=1_000_000_000, bnb_usd=600.0)
    assert math.isclose(got, 118387 * 1e9 * 600 / 1e18, rel_tol=1e-12)


def test_gas_cost_usd_raises_for_unmeasured():
    with pytest.raises(calibrate.GasUnitUnmeasured):
        calibrate.gas_cost_usd("v3_mint")
    with pytest.raises(calibrate.GasUnitUnmeasured):
        calibrate.gas_cost_usd("does_not_exist")


@pytest.mark.live
def test_gas_cost_usd_live_defaults():
    cost = calibrate.gas_cost_usd("approve")
    assert 0 < cost < 5.0  # an approve on BSC is cents
