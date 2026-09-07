"""Paper simulation of pcs-rebalancer over a real pool price path (spec.md §6).

Hold a v3 range; at each checkpoint (or when price exits the range) apply the
cost-aware rule from economics.py. Accrue fees while in range; crystallise IL +
gas on each rebalance. `net_fees_usd` (fees - gas - IL, realised + open) is the
metric compared against the `static_range` baseline.

Every checkpoint — rebalance OR hold — is logged with its arithmetic (§6.2: the
decision *not* to act, with the numbers, is a first-class output).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from data.calibrate import il_estimate

from .economics import concentration_factor, rebalance_decision
from .range import RangeConfig, select_range

_HOUR_YEARS = 1.0 / 8760.0


@dataclass
class RebalancerSimResult:
    net_fees_usd: float
    accrued_fees_usd: float
    total_gas_usd: float
    realised_il_usd: float
    unrealised_il_usd: float
    n_rebalances: int
    n_holds: int
    in_range_fraction: float
    window_days: float
    final_range: dict
    decisions: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["decisions"] = self.decisions[-40:]
        return d


def simulate_rebalancer(
    klines: pd.DataFrame,
    initial_range: RangeConfig,
    *,
    capital_usd: float,
    fee_apr_base: float,
    gas_open_usd: float,
    gas_close_usd: float,
    checkpoint_hours: int = 24,
) -> RebalancerSimResult:
    rng = initial_range
    risk, fee_tier, spacing, horizon = rng.risk, rng.fee_tier, rng.spacing, rng.horizon_days

    close = klines["close"].to_numpy(dtype=float)
    ts = (pd.to_datetime(klines["open_time"]).astype("int64") // 1_000_000).to_numpy()
    n = len(close)

    accrued_fees = 0.0
    total_gas = gas_open_usd            # the initial mint
    realised_il = 0.0
    n_reb = 0
    n_hold = 0
    in_range_hours = 0
    open_idx = 0
    decisions: list[dict] = []

    for idx in range(n):
        price = close[idx]
        in_range = rng.pa <= price <= rng.pb
        if in_range:
            in_range_hours += 1
            accrued_fees += capital_usd * fee_apr_base * concentration_factor(
                rng.half_width_frac) * _HOUR_YEARS

        checkpoint = idx > 0 and (idx % checkpoint_hours == 0 or not in_range)
        if not checkpoint or idx < 24:
            continue

        window = klines.iloc[max(0, idx - 720): idx + 1]
        new_rng = select_range(window, price, risk, fee_tier=fee_tier,
                               horizon_days=horizon, spacing=spacing)
        elapsed_days = (idx - open_idx) / 24.0
        dec = rebalance_decision(
            capital_usd=capital_usd, fee_apr_base=fee_apr_base,
            new_half_width_frac=new_rng.half_width_frac, vol_annual=new_rng.vol_annual,
            horizon_days=horizon, elapsed_days=elapsed_days,
            current_half_width_frac=rng.half_width_frac,
            gas_close_usd=gas_close_usd, gas_open_usd=gas_open_usd,
        )
        decisions.append({
            "idx": idx, "ts": int(ts[idx]), "price": price, "in_range": in_range,
            **dec.as_dict(),
        })
        if dec.act:
            realised_il += dec.realised_il_usd
            total_gas += gas_close_usd + gas_open_usd
            rng = new_rng
            open_idx = idx
            n_reb += 1
        else:
            n_hold += 1

    final_elapsed_days = (n - 1 - open_idx) / 24.0
    unrealised_il = il_estimate(
        rng.vol_annual, max(final_elapsed_days, 0.01), rng.half_width_frac
    ) * capital_usd
    net = accrued_fees - total_gas - realised_il - unrealised_il
    window_days = (ts[-1] - ts[0]) / 86_400_000 if n > 1 else 0.0

    return RebalancerSimResult(
        net_fees_usd=net,
        accrued_fees_usd=accrued_fees,
        total_gas_usd=total_gas,
        realised_il_usd=realised_il,
        unrealised_il_usd=unrealised_il,
        n_rebalances=n_reb,
        n_holds=n_hold,
        in_range_fraction=in_range_hours / n if n else 0.0,
        window_days=window_days,
        final_range=rng.as_dict(),
        decisions=decisions,
    )
