"""Calibration functions — pure functions over REAL data only (rule R3).

Implemented in T-012. Signatures match spec.md §2 exactly. Each will return a
value plus the inputs that produced it, for the snapshot hash.

Never call this "training" or "a model" — it is calibration: computing strategy
parameters from recent real data (context.md §7).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

_TODO = "not implemented until T-012"


def atr(klines: Sequence[Any], period: int = 14) -> float:
    """Wilder ATR on 1h candles."""
    raise NotImplementedError(_TODO)


def realized_vol(klines: Sequence[Any], window_hours: int = 720) -> float:
    """Stdev of log returns, annualised. 30d default."""
    raise NotImplementedError(_TODO)


def fee_apr(pool_day_datas: Sequence[Any], days: int = 30) -> float:
    """sum(feesUSD[-days:]) / mean(tvlUSD[-days:]) * 365/days."""
    raise NotImplementedError(_TODO)


def il_estimate(vol_annual: float, horizon_days: float, range_width_pct: float) -> float:
    """Expected impermanent loss % for a bounded v3 range under a lognormal price
    assumption. The formula and its assumptions get documented inline in T-012."""
    raise NotImplementedError(_TODO)


def gas_cost_usd(op: str) -> float:
    """live gas price x gas units per op. Gas units MUST be measured on the Anvil
    fork (fixtures/gas_units.json), never hardcoded (spec.md §2)."""
    raise NotImplementedError(_TODO)
