"""pcs-yield net-APR maths (spec.md §4.1). Pure — no I/O.

    net_apr = fee_apr
            + emission_apr * decay_factor(horizon)
            - expected_il(vol, horizon, range)        [annualised]
            - amortised_gas(entry+exit, capital, horizon)
            - dilution_adjustment(tvl_trend)

Every term is returned separately so the UI can show "headline X% -> net Y%"
with the subtraction visible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from data.calibrate import il_estimate

_DAYS_PER_YEAR = 365.0
# v2 full-range LP: il_estimate is written for bounded v3 ranges; a very wide
# range recovers the v2 result E[2*sqrt(k)/(1+k) - 1].
V2_RANGE_WIDTH = 50.0


def emission_decay_factor(horizon_days: float, half_life_days: float = 90.0) -> float:
    """Average of an exponentially-decaying emission rate over [0, horizon].
    rate(t) = 2 ** (-t / half_life); the mean over the horizon is
    hl / (H ln2) * (1 - 2**(-H/hl)). -> 1 as H -> 0, -> 0 as H -> inf."""
    if horizon_days <= 0:
        return 1.0
    hl = max(half_life_days, 1e-6)
    x = horizon_days / hl
    return hl / (horizon_days * math.log(2)) * (1.0 - math.pow(2.0, -x))


def dilution_adjustment(
    fee_apr_pct: float, tvl_now: float, tvl_14d_ago: float | None, horizon_days: float
) -> float:
    """Per-unit fee yield scales ~1/TVL. Project TVL forward from its 14-day
    growth rate; the average yield over the horizon is fee_apr * tvl_now /
    tvl_avg_future. The drag is the difference. Returns a **positive** pct to
    subtract, clamped to [0, fee_apr]."""
    if not tvl_14d_ago or tvl_14d_ago <= 0 or tvl_now <= 0 or fee_apr_pct <= 0:
        return 0.0
    g14 = tvl_now / tvl_14d_ago  # growth factor over 14 days
    if g14 <= 1.0:
        return 0.0  # flat or shrinking TVL -> no dilution drag
    daily = g14 ** (1.0 / 14.0)
    # average TVL over the horizon relative to now, assuming continued growth
    n = max(horizon_days, 1.0)
    tvl_avg_rel = sum(daily ** t for t in range(int(n))) / n if n >= 1 else 1.0
    tvl_avg_rel = max(tvl_avg_rel, 1.0)
    drag = fee_apr_pct * (1.0 - 1.0 / tvl_avg_rel)
    return max(0.0, min(drag, fee_apr_pct))


@dataclass(frozen=True)
class NetApr:
    pool: str
    symbol: str
    fee_apr: float
    emission_apr_effective: float
    il_annual: float
    gas_annual: float
    dilution: float
    net_apr: float
    headline_apr: float
    il_verified: bool = True
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "pool": self.pool, "symbol": self.symbol,
            "headline_apr_pct": round(self.headline_apr, 3),
            "fee_apr_pct": round(self.fee_apr, 3),
            "emission_apr_effective_pct": round(self.emission_apr_effective, 3),
            "expected_il_annual_pct": round(self.il_annual, 3),
            "amortised_gas_annual_pct": round(self.gas_annual, 4),
            "dilution_pct": round(self.dilution, 3),
            "net_apr_pct": round(self.net_apr, 3),
            "il_verified": self.il_verified,
            "notes": self.notes,
        }


def net_apr(
    *,
    pool: str,
    symbol: str,
    fee_apr_pct: float,
    emission_apr_pct: float,
    headline_apr_pct: float,
    horizon_days: float,
    vol_annual: float | None,
    capital_usd: float,
    gas_usd_roundtrip: float,
    tvl_now: float,
    tvl_14d_ago: float | None,
    range_width: float = V2_RANGE_WIDTH,
) -> NetApr:
    notes: list[str] = []

    if vol_annual is None:
        il_annual = 0.0
        il_verified = False
        notes.append("IL not estimated — no price history for this pair")
    else:
        il_frac = il_estimate(vol_annual, horizon_days, range_width)
        il_annual = il_frac * _DAYS_PER_YEAR / max(horizon_days, 1e-6) * 100.0
        il_verified = True

    gas_annual = (
        gas_usd_roundtrip / max(capital_usd, 1e-6)
        * _DAYS_PER_YEAR / max(horizon_days, 1e-6) * 100.0
    )
    emission_eff = emission_apr_pct * emission_decay_factor(horizon_days)
    dilution = dilution_adjustment(fee_apr_pct, tvl_now, tvl_14d_ago, horizon_days)

    net = fee_apr_pct + emission_eff - il_annual - gas_annual - dilution
    return NetApr(
        pool=pool, symbol=symbol, fee_apr=fee_apr_pct,
        emission_apr_effective=emission_eff, il_annual=il_annual,
        gas_annual=gas_annual, dilution=dilution, net_apr=net,
        headline_apr=headline_apr_pct, il_verified=il_verified, notes=notes,
    )
