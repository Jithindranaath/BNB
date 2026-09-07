"""Grid calibration for bnb-grid (spec.md §5.1).

    spacing_frac = k(risk) * atr(klines_1h, 14) / mid_price   # k: tight .5 balanced 1.0 wide 1.75
    lower/upper  = 10th / 90th percentile of close over the calibration window
    levels       = clamp(user_levels, 5, 30)
    size/level   = capital_usd / levels

Pure function of the candle frame — no I/O, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from data.calibrate import atr

_K = {"tight": 0.5, "balanced": 1.0, "wide": 1.75}
MIN_LEVELS, MAX_LEVELS = 5, 30


@dataclass(frozen=True)
class GridConfig:
    lower: float
    upper: float
    levels: int
    lines: tuple[float, ...]
    size_usd_per_level: float
    spacing_frac: float          # k*atr/mid — used by the circuit breaker (§5.3)
    atr: float
    mid_price: float
    risk: str
    capital_usd: float

    def as_dict(self) -> dict:
        return {
            "lower": self.lower, "upper": self.upper, "levels": self.levels,
            "lines": list(self.lines), "size_usd_per_level": self.size_usd_per_level,
            "spacing_frac": self.spacing_frac, "atr": self.atr,
            "mid_price": self.mid_price, "risk": self.risk, "capital_usd": self.capital_usd,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GridConfig:
        return cls(
            lower=d["lower"], upper=d["upper"], levels=int(d["levels"]),
            lines=tuple(d["lines"]), size_usd_per_level=d["size_usd_per_level"],
            spacing_frac=d["spacing_frac"], atr=d["atr"], mid_price=d["mid_price"],
            risk=d["risk"], capital_usd=d["capital_usd"],
        )


def clamp_levels(user_levels: int) -> int:
    return max(MIN_LEVELS, min(MAX_LEVELS, int(user_levels)))


def calibrate_grid(
    klines: pd.DataFrame,
    capital_usd: float,
    user_levels: int,
    risk: str,
) -> GridConfig:
    if risk not in _K:
        raise ValueError(f"risk must be one of {sorted(_K)}")
    if len(klines) < 20:
        raise ValueError("need >= 20 candles to calibrate a grid")

    close = klines["close"].to_numpy(dtype=float)
    mid = float(close[-1])
    atr_v = atr(klines, period=14)
    spacing_frac = _K[risk] * atr_v / mid

    lower = float(np.percentile(close, 10))
    upper = float(np.percentile(close, 90))
    if not (lower < mid < upper):
        # price is outside the 10-90 band right now; widen to include it
        lower = min(lower, mid * (1 - 3 * spacing_frac))
        upper = max(upper, mid * (1 + 3 * spacing_frac))

    levels = clamp_levels(user_levels)
    lines = tuple(float(x) for x in np.linspace(lower, upper, levels))
    return GridConfig(
        lower=lower, upper=upper, levels=levels, lines=lines,
        size_usd_per_level=capital_usd / levels,
        spacing_frac=spacing_frac, atr=atr_v, mid_price=mid, risk=risk,
        capital_usd=capital_usd,
    )
