"""The cost-aware rebalance rule — the actual intelligence of pcs-rebalancer
(spec.md §6.2).

Do NOT rebalance just because the position went out of range. Rebalance only when

    expected_fees(next_horizon, new_range) - realised_il_on_close - gas_cost(close+open) > 0

Otherwise hold, and report the arithmetic ("holding: rebalance not economic,
would cost $X vs $Y expected"). Pure functions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from data.calibrate import il_estimate

# Cap the v3 concentration multiplier so a razor-thin range can't imply absurd fees.
MAX_CONCENTRATION = 50.0


def concentration_factor(half_width_frac: float) -> float:
    """How much more fee-earning liquidity a bounded range packs vs a full-range
    position of the same capital. Standard v3 capital-efficiency approximation
    for a range of price * exp(+/- hw): C ~= 1 / (1 - exp(-hw/2)).
    hw=0.10 -> ~20x, hw=0.50 -> ~4.5x, hw=1.0 -> ~2.5x."""
    if half_width_frac <= 0:
        return MAX_CONCENTRATION
    c = 1.0 / (1.0 - math.exp(-half_width_frac / 2.0))
    return min(c, MAX_CONCENTRATION)


def expected_fees_usd(
    *, capital_usd: float, fee_apr_base: float, half_width_frac: float,
    horizon_days: float, in_range_frac: float = 1.0,
) -> float:
    """Fees a freshly centred range would earn over the next horizon (assumed
    mostly in range since we just re-centred)."""
    c = concentration_factor(half_width_frac)
    return capital_usd * fee_apr_base * c * in_range_frac * horizon_days / 365.0


@dataclass
class RebalanceDecision:
    act: bool
    expected_fees_usd: float
    realised_il_usd: float
    gas_cost_usd: float
    net_usd: float
    reason: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def rebalance_decision(
    *,
    capital_usd: float,
    fee_apr_base: float,
    new_half_width_frac: float,
    vol_annual: float,
    horizon_days: float,
    elapsed_days: float,
    current_half_width_frac: float,
    gas_close_usd: float,
    gas_open_usd: float,
) -> RebalanceDecision:
    fees = expected_fees_usd(
        capital_usd=capital_usd, fee_apr_base=fee_apr_base,
        half_width_frac=new_half_width_frac, horizon_days=horizon_days,
    )
    # IL crystallised by closing the current position now
    il = il_estimate(vol_annual, max(elapsed_days, 0.01), current_half_width_frac) * capital_usd
    gas = gas_close_usd + gas_open_usd
    net = fees - il - gas
    act = net > 0
    if act:
        reason = (f"rebalance: expected fees ${fees:.2f} - realised IL ${il:.2f} "
                  f"- gas ${gas:.2f} = ${net:+.2f}")
    else:
        reason = (f"holding: rebalance not economic — would cost ${il + gas:.2f} "
                  f"(IL ${il:.2f} + gas ${gas:.2f}) vs ${fees:.2f} expected fees "
                  f"(net ${net:+.2f})")
    return RebalanceDecision(act, fees, il, gas, net, reason)
