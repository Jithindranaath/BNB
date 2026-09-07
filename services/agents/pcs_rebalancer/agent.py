"""pcs-rebalancer (rebalancing, Tiers 1 & 2).

Tier 1 (T-042): paper. observe() reads the pool (token pair, fee tier, current
tick) + its fee APR from DefiLlama + BNB/USDT klines for volatility; decide()
selects a range (§6.1, pure); act() runs the paper sim with the cost-aware
rebalance rule (§6.2 — every hold is logged with its arithmetic); report() ->
net_fees_usd vs the `static_range` baseline.

Tier 2 (T-043): the same decide(); act() drives the NonfungiblePositionManager
(npm.py) when the session-key signer carries a live web3 + account. The full
open->adjust->close lifecycle + gas is proven on an Anvil fork
(scripts/measure_v3_gas.py, tests/test_v3_position.py); a mainnet dry run needs
a funded scoped key.

Scope: pools that pair WBNB with a USD stable (USDT/USDC/BUSD) — the price path
comes from BNB/USDT klines. Other pairs raise a clear error for now.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yaml
from data import cache, reference
from data.calibrate import gas_cost_usd, realized_vol
from data.sources import llama, rpc

from agents.base import Actions, Agent, Decision, ExecContext, Observation, Result, canonical_hash
from agents.manifest import Manifest

from .npm import open_position
from .range import RangeConfig, select_range
from .sim import simulate_rebalancer

_MF = Manifest.model_validate(
    yaml.safe_load((Path(__file__).parent / "manifest.yaml").read_text())
)

_STABLES = {
    reference.token_address("USDT").lower(),
    reference.token_address("USDC").lower(),
    reference.token_address("BUSD").lower(),
}
_WBNB = reference.token_address("WBNB").lower()


class UnsupportedPool(ValueError):
    pass


def _fee_apr_from_defillama(token0: str, token1: str, fee_tier: int) -> tuple[float, str]:
    want = {token0.lower(), token1.lower()}
    pools = llama.get_pools(chain="BSC", project="pancakeswap")
    cands = [
        p for p in pools
        if p.underlying_tokens and {t.lower() for t in p.underlying_tokens} == want
    ]
    if not cands:
        raise UnsupportedPool(f"DefiLlama has no PancakeSwap BSC pool for {want}")
    cands.sort(key=lambda p: (p.pool_meta == f"{fee_tier / 10000:.2%}", p.tvl_usd or 0), reverse=True)
    top = cands[0]
    apr = (top.apy_base if top.apy_base is not None else top.apy) or 0.0
    return apr / 100.0, top.pool


def _prices_from_klines(df: pd.DataFrame, invert: bool) -> list[float]:
    c = df["close"].to_numpy(dtype=float)
    return [(1.0 / x) for x in c] if invert else [float(x) for x in c]


class PcsRebalancerAgent(Agent):
    manifest = _MF

    def __init__(
        self, *, since_ms: int | None = None, calib_days: int = 30,
        horizon_days: float = 7.0, checkpoint_hours: int = 24, default_window_days: int = 7,
    ) -> None:
        self.since_ms = since_ms
        self.calib_days = calib_days
        self.horizon_days = horizon_days
        self.checkpoint_hours = checkpoint_hours
        self.default_window_days = default_window_days
        self._obs_data: dict = {}
        self._sim = None

    # ---- observe -------------------------------------------------

    def observe(self, inputs: dict) -> Observation:
        pool = str(inputs["pool"])
        st = rpc.pancake_v3_pool_state(pool)
        t0, t1 = st.token0.lower(), st.token1.lower()
        if _WBNB not in (t0, t1) or not ({t0, t1} & _STABLES):
            raise UnsupportedPool(f"pool {pool}: only WBNB/<USD stable> pools are supported")
        invert = t0 in _STABLES          # pool price is token1/token0; if token0 is the stable -> BNB per USD

        klines_pair = "BNB-USDT"
        calib_df = cache.read_klines(klines_pair, "1h", days=self.calib_days).reset_index(drop=True)
        if self.since_ms is not None:
            cutoff = pd.Timestamp(self.since_ms, unit="ms", tz="UTC")
            sim_df = calib_df[calib_df["open_time"] >= cutoff]
        else:
            sim_df = calib_df.tail(self.default_window_days * 24)
        if len(sim_df) < 26:  # too short to reach a checkpoint — fall back to ~2 days
            sim_df = calib_df.tail(48)
        sim_df = sim_df.reset_index(drop=True)

        # price series in pool (token1/token0) units
        calib_pool_close = _prices_from_klines(calib_df, invert)
        sim_pool_df = sim_df.copy()
        for col in ("open", "high", "low", "close"):
            sim_pool_df[col] = [(1.0 / x) if invert else float(x) for x in sim_df[col]]

        fee_apr_base, dl_pool = _fee_apr_from_defillama(st.token0, st.token1, st.fee)
        raw_price = 1.0001**st.tick   # 18/18 pools; decimals adj would go here otherwise
        vol_annual = realized_vol(calib_df, window_hours=720)  # scale-invariant under inversion

        gas_open = gas_cost_usd("v3_mint")
        gas_close = (gas_cost_usd("v3_decrease_liquidity") + gas_cost_usd("v3_collect")
                     + gas_cost_usd("v3_burn"))

        data = {
            "inputs": dict(inputs),
            "pool": pool, "token0": st.token0, "token1": st.token1,
            "fee_tier": st.fee, "tick_spacing": st.tick_spacing, "tick": st.tick,
            "invert": invert, "raw_price": raw_price,
            "fee_apr": fee_apr_base, "defillama_pool_id": dl_pool,
            "vol_annual": vol_annual,
            "horizon_days": self.horizon_days,
            "gas_open_usd": gas_open, "gas_close_usd": gas_close,
            "calib_pool_close": calib_pool_close,
            "calib_open_time_ms": [int(pd.Timestamp(t).timestamp() * 1000)
                                   for t in calib_df["open_time"]],
            "sim_pool_klines": [
                {"open_time_ms": int(pd.Timestamp(r.open_time).timestamp() * 1000),
                 "open": float(r.open), "high": float(r.high), "low": float(r.low),
                 "close": float(r.close)}
                for r in sim_pool_df.itertuples(index=False)
            ],
        }
        self._obs_data = data
        return Observation(data=data, snapshot_hash=canonical_hash(data))

    # ---- decide (pure) -----------------------------------------

    def _calib_df(self, d: dict) -> pd.DataFrame:
        df = pd.DataFrame({
            "close": d["calib_pool_close"],
            "high": d["calib_pool_close"], "low": d["calib_pool_close"],
        })
        df["open_time"] = pd.to_datetime(d["calib_open_time_ms"], unit="ms", utc=True)
        return df

    def decide(self, obs: Observation) -> Decision:
        d = obs.data
        rng = select_range(
            self._calib_df(d), raw_price=float(d["raw_price"]),
            risk=str(d["inputs"].get("risk", "balanced")),
            fee_tier=int(d["fee_tier"]), horizon_days=float(d["horizon_days"]),
            spacing=int(d["tick_spacing"]),
        )
        return Decision(
            kind="v3_range",
            params={"range": rng.as_dict()},
            rationale=f"ticks [{rng.tick_lower}, {rng.tick_upper}] "
                      f"(+/-{rng.half_width_frac:.1%}), vol {rng.vol_annual:.0%}",
        )

    # ---- act -------------------------------------------------

    def act(self, d: Decision, ctx: ExecContext) -> Actions:
        rng = RangeConfig.from_dict(d.params["range"])
        data = self._obs_data
        sim_df = pd.DataFrame(data["sim_pool_klines"])
        sim_df["open_time"] = pd.to_datetime(sim_df["open_time_ms"], unit="ms", utc=True)

        if ctx.tier < 2:
            self._sim = simulate_rebalancer(
                sim_df, rng,
                capital_usd=float(data["inputs"]["capital_usd"]),
                fee_apr_base=float(data["fee_apr"]),
                gas_open_usd=float(data["gas_open_usd"]),
                gas_close_usd=float(data["gas_close_usd"]),
                checkpoint_hours=self.checkpoint_hours,
            )
            return Actions(performed=self._sim.decisions[-10:], tx_hashes=[])

        # Tier 2 — execute via the NonfungiblePositionManager.
        signer = ctx.require_signer()
        w3 = getattr(signer, "w3", None)
        account = getattr(signer, "account", None)
        if w3 is None or account is None:
            return Actions(performed=[{"plan": "mint " + d.rationale,
                                       "note": "dry run — signer has no live web3/account"}])
        token0, token1 = data["token0"], data["token1"]
        e0 = w3.eth.contract(address=w3.to_checksum_address(token0), abi=reference.abi("erc20"))
        e1 = w3.eth.contract(address=w3.to_checksum_address(token1), abi=reference.abi("erc20"))
        pos = open_position(
            w3, account, token0=token0, token1=token1, fee=int(data["fee_tier"]),
            tick_lower=rng.tick_lower, tick_upper=rng.tick_upper,
            amount0=e0.functions.balanceOf(account).call() // 3,
            amount1=e1.functions.balanceOf(account).call() // 3,
        )
        return Actions(
            performed=[{"open": {"token_id": pos.token_id, "liquidity": pos.liquidity,
                                 "amount0": pos.amount0, "amount1": pos.amount1}}],
            tx_hashes=[],
        )

    # ---- report --------------------------------------------

    def report(self, d: Decision, a: Actions) -> Result:
        if self._sim is None:  # tier 2 path
            return Result(
                metric=self.manifest.advantage_metric.name, unit=self.manifest.advantage_metric.unit,
                value=0.0, outputs={"range": d.params["range"], "actions": a.performed},
            )
        s = self._sim
        return Result(
            metric=self.manifest.advantage_metric.name,   # net_fees_usd
            unit=self.manifest.advantage_metric.unit,       # USD
            value=s.net_fees_usd,
            outputs={
                "range": d.params["range"],
                "stats": {
                    "n_rebalances": s.n_rebalances, "n_holds": s.n_holds,
                    "in_range_fraction": s.in_range_fraction,
                    "accrued_fees_usd": s.accrued_fees_usd,
                    "total_gas_usd": s.total_gas_usd,
                    "realised_il_usd": s.realised_il_usd,
                    "unrealised_il_usd": s.unrealised_il_usd,
                    "window_days": s.window_days,
                },
                "decisions": s.decisions[-40:],   # §6.2: the arithmetic, incl. every hold
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
