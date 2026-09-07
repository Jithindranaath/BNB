"""Calibration functions — pure functions over REAL data only (rule R3).

"Calibration" = computing strategy parameters from recent real data. NOT training,
NOT prediction (context.md §7).

Inputs are pandas frames / plain sequences so these stay trivially testable
against a frozen fixture. Each returns a plain float. No I/O except
`gas_cost_usd`, which is explicitly a live-price helper.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_HOURS_PER_YEAR = 24 * 365  # 8760
_DAYS_PER_YEAR = 365
_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _closes(klines: pd.DataFrame | Sequence[Any]) -> np.ndarray:
    if isinstance(klines, pd.DataFrame):
        return klines["close"].to_numpy(dtype=float)
    return np.array([float(getattr(k, "close", k["close"])) for k in klines], dtype=float)


def _hlc(klines: pd.DataFrame | Sequence[Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if isinstance(klines, pd.DataFrame):
        return (
            klines["high"].to_numpy(dtype=float),
            klines["low"].to_numpy(dtype=float),
            klines["close"].to_numpy(dtype=float),
        )
    h = np.array([float(getattr(k, "high", k["high"])) for k in klines], dtype=float)
    low = np.array([float(getattr(k, "low", k["low"])) for k in klines], dtype=float)
    c = np.array([float(getattr(k, "close", k["close"])) for k in klines], dtype=float)
    return h, low, c


# --------------------------------------------------------------------------
# spec.md §2
# --------------------------------------------------------------------------

def atr(klines: pd.DataFrame | Sequence[Any], period: int = 14) -> float:
    """Wilder's Average True Range, in price units, on the given candles.

    TR_t = max( high_t - low_t,
                |high_t - close_{t-1}|,
                |low_t  - close_{t-1}| )
    ATR is Wilder-smoothed: seed = mean(TR[1 : period+1]); then
        ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period
    Returns the final ATR value.
    """
    high, low, close = _hlc(klines)
    n = len(close)
    if n < period + 1:
        raise ValueError(f"need > {period} candles for ATR({period}), got {n}")

    prev_close = close[:-1]
    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - prev_close),
        np.abs(low[1:] - prev_close),
    ])

    atr_val = float(tr[:period].mean())
    for t in range(period, len(tr)):
        atr_val = (atr_val * (period - 1) + tr[t]) / period
    return atr_val


def realized_vol(klines: pd.DataFrame | Sequence[Any], window_hours: int = 720) -> float:
    """Annualised realised volatility from 1h close-to-close log returns.

    Uses the last `window_hours` candles (default 30d). stdev is sample (ddof=1)
    of ln(c_t / c_{t-1}); annualised by sqrt(8760) since the candles are hourly.
    Returned as a fraction (0.65 == 65% annualised).
    """
    close = _closes(klines)
    close = close[-(window_hours + 1):] if window_hours else close
    if len(close) < 3:
        raise ValueError("need >= 3 closes for realized_vol")
    logret = np.diff(np.log(close))
    return float(logret.std(ddof=1) * math.sqrt(_HOURS_PER_YEAR))


def fee_apr(pool_day_datas: Sequence[Any], days: int = 30) -> float:
    """Fee APR of a pool from its daily fee + TVL history.

        sum(feesUSD[-days:]) / mean(tvlUSD[-days:]) * 365 / days

    Accepts subgraph `PoolDayData` models, dicts with `feesUSD`/`tvlUSD`, or
    dicts with `fees_usd`/`tvl_usd`. Returned as a fraction (0.31 == 31% APR).
    """
    def _f(row: Any, *names: str) -> float:
        for nm in names:
            if hasattr(row, nm):
                return float(getattr(row, nm))
            if isinstance(row, dict) and nm in row:
                return float(row[nm])
        raise KeyError(f"row missing any of {names}: {row!r}")

    window = list(pool_day_datas)[-days:]
    if not window:
        raise ValueError("no pool day data")
    fees = sum(_f(r, "fees_usd", "feesUSD") for r in window)
    tvl_mean = sum(_f(r, "tvl_usd", "tvlUSD") for r in window) / len(window)
    if tvl_mean <= 0:
        raise ValueError("non-positive mean TVL")
    return fees / tvl_mean * _DAYS_PER_YEAR / len(window)


# --- v3 impermanent loss ---------------------------------------------------

def _v3_amounts(L: float, p: float, pa: float, pb: float) -> tuple[float, float]:
    """Token amounts (x = base, y = quote) held by `L` units of v3 liquidity at
    price `p` for the range [pa, pb]. Uniswap v3 whitepaper eqs 6.29–6.30, with
    the position fully in one asset outside the range."""
    sp, spa, spb = math.sqrt(p), math.sqrt(pa), math.sqrt(pb)
    if p <= pa:
        return L * (spb - spa) / (spa * spb), 0.0
    if p >= pb:
        return 0.0, L * (spb - spa)
    return L * (spb - sp) / (sp * spb), L * (sp - spa)


def il_estimate(vol_annual: float, horizon_days: float, range_width_pct: float) -> float:
    """Expected impermanent loss of a bounded Uniswap/PancakeSwap v3 range
    position over `horizon_days`, as a positive fraction of the held value.

    Assumptions (stated because they matter):
      * Entry price p0 = 1 (WLOG). The range is linear-symmetric about p0:
        [pa, pb] = [p0 * (1 - w), p0 * (1 + w)] with w = range_width_pct.
      * Terminal price ratio k = p_T / p0 is lognormal with **zero drift**:
        ln k ~ N(-0.5 s^2, s^2), s = vol_annual * sqrt(horizon_days / 365),
        so E[k] = 1 (no view on direction; this is a risk estimate, not a forecast).
      * No fees, no rebalancing within the horizon.
    Method: IL(k) = 1 - V_lp(k) / V_hold(k), then E[IL] via numerical
    integration of IL(k) against the lognormal density on a log-spaced grid.
    A wider range -> smaller IL; range_width_pct -> inf recovers the v2 result
    E[2 sqrt(k)/(1+k) - 1].
    """
    if not (0 < range_width_pct):
        raise ValueError("range_width_pct must be > 0")
    w = min(range_width_pct, 0.999999)  # pa must stay > 0
    p0, pa, pb = 1.0, 1.0 - w, 1.0 + w

    # unit-capital liquidity: pick L so V_hold at entry == 1 (x0*p0 + y0 == 1)
    x0, y0 = _v3_amounts(1.0, p0, pa, pb)
    L = 1.0 / (x0 * p0 + y0)
    x0, y0 = x0 * L, y0 * L

    s = vol_annual * math.sqrt(horizon_days / _DAYS_PER_YEAR)
    if s <= 0:
        return 0.0
    mu = -0.5 * s * s

    # log-spaced k grid spanning +/- 8 sigma
    lo, hi = mu - 8 * s, mu + 8 * s
    ln_k = np.linspace(lo, hi, 4001)
    k = np.exp(ln_k)
    pdf_lnk = np.exp(-((ln_k - mu) ** 2) / (2 * s * s)) / (s * math.sqrt(2 * math.pi))

    il = np.empty_like(k)
    for i, ki in enumerate(k):
        x, y = _v3_amounts(L, ki, pa, pb)
        v_lp = x * ki + y
        v_hold = x0 * ki + y0
        il[i] = 1.0 - v_lp / v_hold

    expected = float(np.trapezoid(il * pdf_lnk, ln_k))
    return max(expected, 0.0)


# --- gas ----------------------------------------------------------------

class GasUnitUnmeasured(RuntimeError):
    """Raised when gas units for an op have not been measured on the fork yet
    (rule R6 — do not return a guessed number that renders in the UI)."""


def _gas_units() -> dict:
    path = _FIXTURES / "gas_units.json"
    if not path.exists():
        raise GasUnitUnmeasured("fixtures/gas_units.json missing — run scripts/measure_gas.py")
    return json.loads(path.read_text())


def gas_cost_usd(op: str, *, gas_price_wei: int | None = None, bnb_usd: float | None = None) -> float:
    """USD cost of one on-chain `op` = gas_units[op] * gas_price * BNB/USD.

    gas_units come from a MEASURED Anvil-fork run (fixtures/gas_units.json); an
    op whose entry is `verified: false` raises GasUnitUnmeasured rather than
    guessing. `gas_price_wei` / `bnb_usd` default to live values.
    """
    units = _gas_units().get("ops", {}).get(op)
    if units is None:
        raise GasUnitUnmeasured(f"no gas_units entry for {op!r}")
    if not units.get("verified"):
        raise GasUnitUnmeasured(f"gas units for {op!r} not measured yet: {units.get('note', '')}")

    if gas_price_wei is None:
        from .sources.rpc import gas_price_wei as _gp

        gas_price_wei = _gp()
    if bnb_usd is None:
        from .sources.binance import spot_price

        bnb_usd = spot_price("BNB-USDT")

    return units["gas"] * gas_price_wei * bnb_usd / 1e18
