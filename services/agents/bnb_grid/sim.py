"""Deterministic paper grid simulation (spec.md §5.2, §5.3, §5.5).

Given a candle path and a calibrated GridConfig, replay slot-by-slot fills at the
grid-line prices with a slippage haircut, a trading fee, and a per-fill gas cost.
Same candles + same grid -> identical SimResult (the harness relies on this).

Model: start all-quote (cash = capital). Slot i buys at lines[i], sells at
lines[i+1]. A slot is only sold on a LATER candle than it was bought (no
same-candle round trips — conservative). Circuit breaker halts the replay if the
unrealised loss exceeds max_loss_pct of capital, or price leaves the calibrated
range by more than 2x the (fractional) spacing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .grid import GridConfig

FEE_BPS = 25.0          # 0.25% — PancakeSwap v2 swap fee
SLIPPAGE_BPS = 10.0     # fills are haircut this much off the line price


@dataclass
class SimResult:
    net_pnl_usd: float
    realized_pnl_usd: float
    unrealized_pnl_usd: float
    n_trades: int
    n_round_trips: int
    win_rate: float
    max_drawdown_pct: float
    capital_at_risk_usd: float
    window_days: float
    fees_usd: float
    gas_usd: float
    halted: bool
    halt_reason: str | None
    final_equity_usd: float
    equity_curve: list[list[float]] = field(default_factory=list)  # [ts_ms, equity]
    round_trips: list[dict] = field(default_factory=list)
    fills: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        # keep the payload small
        d["equity_curve"] = self.equity_curve[:: max(1, len(self.equity_curve) // 200)]
        d["fills"] = self.fills[-50:]
        d["round_trips"] = self.round_trips[-50:]
        return d


def _rows(klines) -> list[tuple[int, float, float, float, float]]:
    if isinstance(klines, pd.DataFrame):
        it = klines.itertuples(index=False)
        out = []
        for r in it:
            ts = int(pd.Timestamp(r.open_time).timestamp() * 1000)
            out.append((ts, float(r.open), float(r.high), float(r.low), float(r.close)))
        return out
    out = []
    for k in klines:
        ts = k.get("open_time_ms")
        if ts is None:
            ts = int(pd.Timestamp(k["open_time"]).timestamp() * 1000)
        out.append((int(ts), float(k["open"]), float(k["high"]), float(k["low"]), float(k["close"])))
    return out


def simulate(
    klines,
    grid: GridConfig,
    *,
    gas_usd_per_fill: float,
    fee_bps: float = FEE_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    max_loss_pct: float = 5.0,
) -> SimResult:
    rows = _rows(klines)
    lines = list(grid.lines)
    capital = grid.capital_usd
    size = grid.size_usd_per_level
    slip = slippage_bps / 1e4
    fee = fee_bps / 1e4

    n_slots = len(lines) - 1
    slots: list[dict | None] = [None] * n_slots

    cash = capital
    fees_usd = 0.0
    gas_usd = 0.0
    fills: list[dict] = []
    round_trips: list[dict] = []
    equity_curve: list[list[float]] = []
    peak = capital
    max_dd = 0.0
    max_inv = 0.0
    halted, halt_reason = False, None

    lo_bound = grid.lower * (1 - 2 * grid.spacing_frac)
    hi_bound = grid.upper * (1 + 2 * grid.spacing_frac)

    for idx, (ts, _o, high, low, close) in enumerate(rows):
        # --- buys: price dipped to an empty slot's line ---
        for i in range(n_slots):
            if slots[i] is None and low <= lines[i] and cash >= size:
                px = lines[i] * (1 + slip)
                qty = size / px
                f = size * fee
                cash -= size + f + gas_usd_per_fill
                fees_usd += f
                gas_usd += gas_usd_per_fill
                cost_basis = size + f + gas_usd_per_fill
                slots[i] = {"buy_px": px, "qty": qty, "buy_idx": idx, "cost_basis": cost_basis}
                fills.append({"idx": idx, "ts": ts, "side": "buy", "line": lines[i],
                              "price": px, "qty": qty, "usd": size})

        # --- sells: price rose to the slot's upper line, on a later candle ---
        for i in range(n_slots):
            s = slots[i]
            if s is not None and idx > s["buy_idx"] and high >= lines[i + 1]:
                px = lines[i + 1] * (1 - slip)
                proceeds = s["qty"] * px
                f = proceeds * fee
                cash += proceeds - f - gas_usd_per_fill
                fees_usd += f
                gas_usd += gas_usd_per_fill
                net = proceeds - f - gas_usd_per_fill - s["cost_basis"]
                round_trips.append({"buy_px": s["buy_px"], "sell_px": px, "qty": s["qty"],
                                    "net_usd": net, "win": net > 0})
                fills.append({"idx": idx, "ts": ts, "side": "sell", "line": lines[i + 1],
                              "price": px, "qty": s["qty"], "usd": proceeds})
                slots[i] = None

        inv_value = sum(s["qty"] * close for s in slots if s is not None)
        equity = cash + inv_value
        equity_curve.append([ts, equity])
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / capital)
        max_inv = max(max_inv, inv_value)

        if (capital - equity) / capital > max_loss_pct / 100:
            halted, halt_reason = True, f"unrealised loss > {max_loss_pct}% of capital"
        elif close > hi_bound or close < lo_bound:
            halted, halt_reason = True, "price left the calibrated range by > 2x spacing"
        if halted:
            break

    last_close = rows[len(equity_curve) - 1][4] if equity_curve else 0.0
    inv_value = sum(s["qty"] * last_close for s in slots if s is not None)
    cost_open = sum(s["cost_basis"] for s in slots if s is not None)
    final_equity = cash + inv_value
    realized = sum(rt["net_usd"] for rt in round_trips)
    unrealized = inv_value - cost_open
    wins = sum(1 for rt in round_trips if rt["win"])
    window_days = (rows[-1][0] - rows[0][0]) / 86_400_000 if len(rows) > 1 else 0.0

    return SimResult(
        net_pnl_usd=final_equity - capital,
        realized_pnl_usd=realized,
        unrealized_pnl_usd=unrealized,
        n_trades=len(fills),
        n_round_trips=len(round_trips),
        win_rate=(wins / len(round_trips)) if round_trips else 0.0,
        max_drawdown_pct=max_dd * 100,
        capital_at_risk_usd=max_inv or 0.0,
        window_days=window_days,
        fees_usd=fees_usd,
        gas_usd=gas_usd,
        halted=halted,
        halt_reason=halt_reason,
        final_equity_usd=final_equity,
        equity_curve=equity_curve,
        round_trips=round_trips,
        fills=fills,
    )
