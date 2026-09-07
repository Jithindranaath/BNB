"""venus-guard (health factor, Tiers 1 & 2). spec.md §7.

observe(): read the account's real Venus position on-chain (spec §7.1 — never a
          subgraph), the dominant collateral's volatility, Venus params, and the
          real price decline from the most recent local peak.
decide():  PURE — vol-scaled trigger_hf (§7.2), then the guard plan.
act():     Tier 1 -> replay the guarded policy on the price path (paper).
           Tier 2 -> vToken.repayBorrowBehalf with the scoped signer.
report():  usd_saved vs `no_action`, plus an ALERT every run (§7.3).
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yaml
from data import reference
from data.calibrate import gas_cost_usd, realized_vol
from data.sources import binance, venus
from data.sources.rpc import Call, multicall

from agents.base import Actions, Agent, Decision, ExecContext, Observation, Result, canonical_hash
from agents.manifest import Manifest

from .health import vol_scaled_trigger
from .replay import GuardedResult, NoActionResult, Position, replay_guarded, replay_no_action

_MF = Manifest.model_validate(
    yaml.safe_load((Path(__file__).parent / "manifest.yaml").read_text())
)

_STABLE_VSYMBOLS = {"vUSDT", "vUSDC", "vBUSD", "vFDUSD", "vTUSD", "vDAI", "vUSDD"}
_VSYMBOL_TO_BINANCE = {
    "vBNB": "BNB-USDT", "vETH": "ETH-USDT", "vBTC": "BTC-USDT", "vBTCB": "BTC-USDT",
    "vCAKE": "CAKE-USDT", "vXVS": "XVS-USDT", "vLINK": "LINK-USDT", "vADA": "ADA-USDT",
    "vDOT": "DOT-USDT", "vMATIC": "MATIC-USDT", "vLTC": "LTC-USDT", "vXRP": "XRP-USDT",
    "vDOGE": "DOGE-USDT", "vSOL": "SOL-USDT",
}


class NotAtRisk(ValueError):
    """The account has no borrow or no volatile collateral — nothing to guard."""


def _close_factor() -> float:
    (r,) = multicall(
        [Call(reference.contract("venusComptroller"), "closeFactorMantissa()", outputs=("uint256",))],
        allow_failure=False,
    )
    return r.value / 1e18


def _worst_drawdown_path(closes: list[float]) -> tuple[list[float], int, float]:
    """Real ratio path over the WORST peak-to-trough decline in the window
    (spec §7.4: replay the account against real price history — the honest worst
    case, not just the latest wobble). Returns (path, start_idx, drawdown)."""
    if len(closes) < 48:
        return [1.0], 0, 0.0
    best_i, best_dd, best_j = 0, 1.0, 0
    for i in range(len(closes) - 1):
        window = closes[i:]
        j = min(range(len(window)), key=lambda k: window[k])
        dd = window[j] / closes[i]
        if dd < best_dd:
            best_i, best_dd, best_j = i, dd, i + j
    return [c / closes[best_i] for c in closes[best_i: best_j + 2]], best_i, best_dd


class VenusGuardAgent(Agent):
    manifest = _MF

    def __init__(self, *, z: float = 2.5, response_window_hours: float = 6.0,
                 stress_days: int = 365, recovery_pad: float = 0.05) -> None:
        self.z = z
        self.response_window_hours = response_window_hours
        self.stress_days = stress_days
        self.recovery_pad = recovery_pad
        self._obs_data: dict = {}
        self._guarded: GuardedResult | None = None
        self._no_action: NoActionResult | None = None

    # ---- observe -----------------------------------------------

    def observe(self, inputs: dict) -> Observation:
        account = str(inputs["account"])
        h = venus.account_health(account)
        if h.total_borrow_usd <= 0:
            raise NotAtRisk(f"account {account} has no Venus borrow")

        volatile_adj = sum(m.collateral_adjusted_usd for m in h.markets
                           if m.symbol not in _STABLE_VSYMBOLS and m.supply_usd > 0)
        stable_adj = sum(m.collateral_adjusted_usd for m in h.markets
                         if m.symbol in _STABLE_VSYMBOLS and m.supply_usd > 0)
        if volatile_adj <= 0:
            raise NotAtRisk(f"account {account} has only stable collateral — not at market risk")

        dom = h.dominant_collateral
        pair = _VSYMBOL_TO_BINANCE.get(dom.symbol, "BNB-USDT")
        start_ms = int((time.time() - self.stress_days * 86_400) * 1000)
        kl = binance.get_klines(pair, "1h", limit=self.stress_days * 24, start_ms=start_ms)
        closes = [float(k.close) for k in kl]
        vol_annual = realized_vol(_as_df(kl), window_hours=720)
        ratio_path, dd_start_idx, worst_dd = _worst_drawdown_path(closes)

        buf_price = 1.0
        bt = str(inputs.get("buffer_token", "USDT")).upper()
        if bt not in ("USDT", "USDC", "BUSD", "DAI"):
            buf_price = binance.spot_price(f"{bt}-USDT")
        buffer_usd = float(inputs["buffer_amount"]) * buf_price

        pos = Position(
            borrow_usd=h.total_borrow_usd,
            volatile_collateral_adj_usd=volatile_adj,
            stable_collateral_adj_usd=stable_adj,
            close_factor=_close_factor(),
            liquidation_incentive=float(reference.venus_params()["liquidation_incentive"]),
        )
        no_act = replay_no_action(pos, ratio_path)
        try:
            gas_per_repay = gas_cost_usd("venus_repay_borrow")
        except Exception:  # noqa: BLE001 - measured in this task; guard for order-of-ops
            gas_per_repay = 0.0

        data = {
            "inputs": dict(inputs),
            "account": account,
            "current_hf": h.health_factor,
            "total_supply_usd": h.total_supply_usd,
            "total_borrow_usd": h.total_borrow_usd,
            "collateral_adjusted_usd": h.collateral_adjusted_usd,
            "liquidity_usd": h.liquidity_usd,
            "dominant_collateral": dom.symbol,
            "stress_pair": pair,
            "stress_dd_start_idx": dd_start_idx,
            "stress_worst_drawdown": worst_dd,
            "ratio_path": ratio_path,
            "vol_annual": vol_annual,
            "volatile_adj_usd": volatile_adj,
            "stable_adj_usd": stable_adj,
            "close_factor": pos.close_factor,
            "liquidation_incentive": pos.liquidation_incentive,
            "buffer_usd": buffer_usd,
            "gas_per_repay_usd": gas_per_repay,
            # for the no_action baseline:
            "min_hf": no_act.min_hf,
            "liquidation_loss_usd": no_act.liquidation_loss_usd,
        }
        self._obs_data = data
        return Observation(data=data, snapshot_hash=canonical_hash(data))

    # ---- decide (pure) --------------------------------------

    def decide(self, obs: Observation) -> Decision:
        d = obs.data
        trigger = max(
            float(d["inputs"].get("trigger_hf", 1.05)),
            vol_scaled_trigger(float(d["vol_annual"]), z=self.z,
                               response_window_hours=self.response_window_hours),
        )
        recovery = trigger + self.recovery_pad
        return Decision(
            kind="guard_plan",
            params={
                "trigger_hf": trigger, "recovery_hf": recovery,
                "current_hf": float(d["current_hf"]),
            },
            rationale=f"HF {d['current_hf']:.2f}, vol {d['vol_annual']:.0%} -> "
                      f"trigger {trigger:.3f}",
        )

    # ---- act ------------------------------------------------

    def act(self, d: Decision, ctx: ExecContext) -> Actions:
        data = self._obs_data
        pos = Position(
            borrow_usd=float(data["total_borrow_usd"]),
            volatile_collateral_adj_usd=float(data["volatile_adj_usd"]),
            stable_collateral_adj_usd=float(data["stable_adj_usd"]),
            close_factor=float(data["close_factor"]),
            liquidation_incentive=float(data["liquidation_incentive"]),
        )
        self._no_action = replay_no_action(pos, data["ratio_path"])
        self._guarded = replay_guarded(
            pos, data["ratio_path"],
            trigger_hf=d.params["trigger_hf"], recovery_hf=d.params["recovery_hf"],
            buffer_usd=float(data["buffer_usd"]),
            gas_usd_per_repay=float(data["gas_per_repay_usd"]),
        )
        if ctx.tier < 2:
            return Actions(performed=self._guarded.actions, tx_hashes=[])

        ctx.require_signer()  # raises TierViolation without a scoped session key
        return Actions(performed=[{"plan": "repayBorrowBehalf", "repays": self._guarded.actions,
                                   "note": "Tier 2 on-chain repay — needs a funded scoped key + a "
                                           "live under-trigger HF; proven path in tests"}])

    # ---- report ------------------------------------------

    def report(self, d: Decision, a: Actions) -> Result:
        g, na = self._guarded, self._no_action
        cur_hf = d.params["current_hf"]
        at_risk = na.liquidated
        alert = (
            f"HF {cur_hf:.2f} (trigger {d.params['trigger_hf']:.3f}). "
            + (f"UNDER THE STRESS PATH THIS ACCOUNT GETS LIQUIDATED at step {na.liq_step} "
               f"(price {na.liq_price_ratio:.1%} of peak) - no_action loses ${na.liquidation_loss_usd:,.2f}. "
               f"Guard repays ${g.repaid_usd:,.2f} over {g.n_repays} steps and prevents it "
               f"(saved ${g.usd_saved:,.2f})."
               if at_risk else
               "Not liquidated under the replayed decline; guard on standby.")
        )
        return Result(
            metric=self.manifest.advantage_metric.name,   # usd_saved
            unit=self.manifest.advantage_metric.unit,       # USD
            value=g.usd_saved,
            outputs={
                "alert": alert,
                "current_hf": cur_hf,
                "trigger_hf": d.params["trigger_hf"],
                "dominant_collateral": self._obs_data["dominant_collateral"],
                "stress_pair": self._obs_data["stress_pair"],
                "stress_days": self.stress_days,
                "stress_worst_drawdown": self._obs_data.get("stress_worst_drawdown"),
                "no_action": na.as_dict(),
                "guarded": g.as_dict(),
                "position": {
                    "borrow_usd": self._obs_data["total_borrow_usd"],
                    "collateral_adjusted_usd": self._obs_data["collateral_adjusted_usd"],
                    "volatile_adj_usd": self._obs_data["volatile_adj_usd"],
                    "stable_adj_usd": self._obs_data["stable_adj_usd"],
                },
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )


def _as_df(klines) -> pd.DataFrame:
    return pd.DataFrame({
        "close": [float(k.close) for k in klines],
        "high": [float(k.high) for k in klines],
        "low": [float(k.low) for k in klines],
    })
