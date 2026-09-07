"""v3 range selection for pcs-rebalancer (spec.md §6.1).

    half_width = m(risk) * realized_vol(klines, 30d) * sqrt(horizon_days/365)   # m: .75/1.25/2.0
    pa, pb     = price * exp(-half_width), price * exp(+half_width)             # log-symmetric
    ticks      = snap_to_spacing(price_to_tick(pa|pb), fee_tier_spacing)

Pure. Prices here are *raw* pool prices (token1 per token0, in wei ratio). The
agent converts a human price with the token decimals before calling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd
from data.calibrate import realized_vol

_M = {"tight": 0.75, "balanced": 1.25, "wide": 2.0}

# PancakeSwap v3 fee tier -> tick spacing
FEE_TIER_SPACING = {100: 1, 500: 10, 2500: 50, 10000: 200}

_LOG_1_0001 = math.log(1.0001)


def price_to_tick(price: float) -> int:
    return math.floor(math.log(price) / _LOG_1_0001)


def tick_to_price(tick: int) -> float:
    return 1.0001**tick


def snap_down(tick: int, spacing: int) -> int:
    return (tick // spacing) * spacing


def snap_up(tick: int, spacing: int) -> int:
    return -((-tick) // spacing) * spacing


@dataclass(frozen=True)
class RangeConfig:
    price: float
    half_width_frac: float
    pa: float
    pb: float
    tick_lower: int
    tick_upper: int
    spacing: int
    fee_tier: int
    risk: str
    horizon_days: float
    vol_annual: float

    @property
    def width_frac(self) -> float:
        """(pb - pa) / price — used by il_estimate and the concentration factor."""
        return (self.pb - self.pa) / self.price

    def as_dict(self) -> dict:
        return {
            "price": self.price, "half_width_frac": self.half_width_frac,
            "pa": self.pa, "pb": self.pb, "tick_lower": self.tick_lower,
            "tick_upper": self.tick_upper, "spacing": self.spacing,
            "fee_tier": self.fee_tier, "risk": self.risk,
            "horizon_days": self.horizon_days, "vol_annual": self.vol_annual,
            "width_frac": self.width_frac,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RangeConfig:
        return cls(
            price=d["price"], half_width_frac=d["half_width_frac"], pa=d["pa"], pb=d["pb"],
            tick_lower=int(d["tick_lower"]), tick_upper=int(d["tick_upper"]),
            spacing=int(d["spacing"]), fee_tier=int(d["fee_tier"]), risk=d["risk"],
            horizon_days=d["horizon_days"], vol_annual=d["vol_annual"],
        )


def select_range(
    klines: pd.DataFrame,
    raw_price: float,
    risk: str,
    *,
    fee_tier: int,
    horizon_days: float = 7.0,
    spacing: int | None = None,
) -> RangeConfig:
    if risk not in _M:
        raise ValueError(f"risk must be one of {sorted(_M)}")
    spacing = spacing or FEE_TIER_SPACING.get(fee_tier)
    if spacing is None:
        raise ValueError(f"unknown fee tier {fee_tier}")

    vol = realized_vol(klines, window_hours=720)
    hw = _M[risk] * vol * math.sqrt(horizon_days / 365.0)
    pa = raw_price * math.exp(-hw)
    pb = raw_price * math.exp(hw)

    tick_lower = snap_down(price_to_tick(pa), spacing)
    tick_upper = snap_up(price_to_tick(pb), spacing)
    if tick_upper <= tick_lower:
        tick_upper = tick_lower + spacing

    return RangeConfig(
        price=raw_price, half_width_frac=hw,
        pa=tick_to_price(tick_lower), pb=tick_to_price(tick_upper),
        tick_lower=tick_lower, tick_upper=tick_upper, spacing=spacing,
        fee_tier=fee_tier, risk=risk, horizon_days=horizon_days, vol_annual=vol,
    )
