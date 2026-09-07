"""Health-factor helpers for venus-guard (spec.md §7.2). Pure."""

from __future__ import annotations

import math

Z_DEFAULT = 2.5
RESPONSE_WINDOW_HOURS_DEFAULT = 6.0


def health_factor(collateral_adjusted_usd: float, borrow_usd: float) -> float:
    if borrow_usd <= 0:
        return math.inf
    return collateral_adjusted_usd / borrow_usd


def vol_scaled_trigger(
    vol_annual: float,
    *,
    z: float = Z_DEFAULT,
    response_window_hours: float = RESPONSE_WINDOW_HOURS_DEFAULT,
) -> float:
    """trigger_hf = 1 + z * sigma_annual * sqrt(response_window_hours / 8760)

    So the guard fires earlier for a violent collateral asset — the buffer scales
    with how far the price can realistically move before the guard can respond,
    rather than a fixed 1.2.
    """
    move = z * vol_annual * math.sqrt(response_window_hours / 8760.0)
    return 1.0 + move
