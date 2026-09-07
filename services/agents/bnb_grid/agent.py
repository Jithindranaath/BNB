"""bnb-grid (grid trading, Tier 1 paper / Tier 2 live).

Tier 1 (this file's focus, T-040): a paper ledger driven by real Binance prices.
observe() pulls 30d of 1h candles for calibration and the candles since the
deployment started for the sim window; decide() calibrates the grid (pure);
act() replays the paper fills; report() -> net_pnl_usd + the §5.5 stats.

Baseline `hodl` runs on the same sim window. Tier 2 (T-041) reuses the same
calibration and drives a real Hummingbot controller instead of the paper sim.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yaml
from data import cache
from data.calibrate import gas_cost_usd

from agents.base import Actions, Agent, Decision, ExecContext, Observation, Result, canonical_hash
from agents.manifest import Manifest

from .grid import GridConfig, calibrate_grid
from .sim import FEE_BPS, SLIPPAGE_BPS, simulate

_MF = Manifest.model_validate(
    yaml.safe_load((Path(__file__).parent / "manifest.yaml").read_text())
)

_KLINE_COLS = ("open", "high", "low", "close", "volume")


def _serialize(df: pd.DataFrame) -> list[dict]:
    out = []
    for r in df.itertuples(index=False):
        out.append({
            "open_time_ms": int(pd.Timestamp(r.open_time).timestamp() * 1000),
            **{c: float(getattr(r, c)) for c in _KLINE_COLS},
        })
    return out


class BnbGridAgent(Agent):
    manifest = _MF

    def __init__(
        self,
        *,
        since_ms: int | None = None,
        calib_days: int = 30,
        default_window_days: int = 7,
        fee_bps: float = FEE_BPS,
        slippage_bps: float = SLIPPAGE_BPS,
    ) -> None:
        self.since_ms = since_ms
        self.calib_days = calib_days
        self.default_window_days = default_window_days
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self._sim_rows: list[dict] = []
        self._gas = 0.0
        self._sim = None

    def observe(self, inputs: dict) -> Observation:
        pair = inputs["pair"]
        calib_df = cache.read_klines(pair, "1h", days=self.calib_days)
        if self.since_ms is not None:
            cutoff = pd.Timestamp(self.since_ms, unit="ms", tz="UTC")
            sim_df = calib_df[calib_df["open_time"] >= cutoff]
        else:
            sim_df = calib_df.tail(self.default_window_days * 24)
        if len(sim_df) < 2:
            sim_df = calib_df.tail(2)

        self._gas = gas_cost_usd("swap_v2")
        self._sim_rows = _serialize(sim_df)

        data = {
            "inputs": dict(inputs),
            "since_ms": self.since_ms,
            "gas_usd_per_fill": self._gas,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "calib_klines": _serialize(calib_df),
            "sim_klines": self._sim_rows,
            "klines": self._sim_rows,  # for the hodl baseline
        }
        return Observation(data=data, snapshot_hash=canonical_hash(data))

    def decide(self, obs: Observation) -> Decision:
        d = obs.data
        calib_df = pd.DataFrame(d["calib_klines"])
        calib_df["open_time"] = pd.to_datetime(calib_df["open_time_ms"], unit="ms", utc=True)
        grid = calibrate_grid(
            calib_df,
            capital_usd=float(d["inputs"]["capital_usd"]),
            user_levels=int(d["inputs"].get("grid_levels", 12)),
            risk=str(d["inputs"].get("risk", "balanced")),
        )
        return Decision(
            kind="grid",
            params={"grid": grid.as_dict()},
            rationale=f"{grid.levels} levels, {grid.lower:.2f}–{grid.upper:.2f}, "
                      f"spacing {grid.spacing_frac:.3%}",
        )

    def act(self, d: Decision, ctx: ExecContext) -> Actions:
        # Tier 1: paper only. (Tier 2 live execution is T-041.)
        grid = GridConfig.from_dict(d.params["grid"])
        self._sim = simulate(
            self._sim_rows, grid,
            gas_usd_per_fill=self._gas,
            fee_bps=self.fee_bps, slippage_bps=self.slippage_bps,
            max_loss_pct=self.manifest.kill_switch.max_loss_pct,
        )
        return Actions(performed=self._sim.fills[-20:], tx_hashes=[])

    def report(self, d: Decision, a: Actions) -> Result:
        s = self._sim
        stats = {
            "win_rate": s.win_rate,
            "n_trades": s.n_trades,
            "n_round_trips": s.n_round_trips,
            "window_days": s.window_days,
            "max_drawdown_pct": s.max_drawdown_pct,
            "capital_at_risk_usd": s.capital_at_risk_usd,
            "realized_pnl_usd": s.realized_pnl_usd,
            "unrealized_pnl_usd": s.unrealized_pnl_usd,
            "fees_usd": s.fees_usd,
            "gas_usd": s.gas_usd,
            "halted": s.halted,
            "halt_reason": s.halt_reason,
            "final_equity_usd": s.final_equity_usd,
        }
        return Result(
            metric=self.manifest.advantage_metric.name,   # net_pnl_usd
            unit=self.manifest.advantage_metric.unit,       # USD
            value=s.net_pnl_usd,
            outputs={
                "grid": d.params["grid"],
                "stats": stats,
                "equity_curve": s.as_dict()["equity_curve"],
                "recent_fills": s.fills[-20:],
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
