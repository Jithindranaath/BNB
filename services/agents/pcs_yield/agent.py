"""pcs-yield (yield optimisation, Tier 0) — spec.md §4.

observe(): DefiLlama pool universe + Binance vol + TVL history + the bsc-sentry
           security gate on the shortlist (all I/O).
decide():  PURE — net_apr per pool (economics.net_apr), drop sentry-CRITICAL
           pools, rank, pick the winner.
act():     nothing (Tier 0).
report():  Result metric `net_apr_delta_pct` vs the `top_headline_apr` baseline;
           the ranked breakdown + the "excluded by security agent" list ride in
           `outputs`.

Data note: DefiLlama currently exposes PancakeSwap **v2** on BSC (no v3 feed).
The richer v3 fee/day data arrives when the Envio HyperIndex indexer is live
(docs/envio-indexer.md) — this agent switches source without changing the maths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from data import reference
from data.calibrate import GasUnitUnmeasured, gas_cost_usd

from agents.base import Actions, Agent, Decision, ExecContext, Observation, Result, canonical_hash
from agents.manifest import Manifest

from . import sources
from .economics import net_apr

_MF = Manifest.model_validate(
    yaml.safe_load((Path(__file__).parent / "manifest.yaml").read_text())
)

# blue-chip BSC tokens the sentry always clears — skip the fork sim for these
_ALLOWLIST: set[str] = {
    reference.token_address(s).lower()
    for s in ("WBNB", "USDT", "USDC", "BUSD", "CAKE")
}
# Binance-Peg majors (verified on-chain in reference/tokens.json notes)
_ALLOWLIST |= {
    "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c",  # BTCB
    "0x2170ed0880ac9a755fd29b2688956bd959f933f8",  # ETH (Binance-Peg)
}

_GATE_DEPTH = {"conservative": 12, "balanced": 8, "degen": 4}


class NoPools(RuntimeError):
    pass


class PcsYieldAgent(Agent):
    manifest = _MF

    def __init__(self, *, min_tvl_usd: float = 50_000.0, universe: int = 15) -> None:
        self.min_tvl_usd = min_tvl_usd
        self.universe = universe
        self._obs_data: dict[str, Any] = {}

    # ---- observe (all I/O) --------------------------------------------

    def observe(self, inputs: dict) -> Observation:
        capital = float(inputs["capital_usd"])
        horizon = float(inputs.get("horizon_days", 30))
        risk = str(inputs.get("risk", "balanced"))

        pools = sources.candidate_pools(min_tvl_usd=self.min_tvl_usd, limit=self.universe)
        if not pools:
            raise NoPools("DefiLlama returned no PancakeSwap BSC pool above the TVL floor")

        try:
            gas_roundtrip = (
                gas_cost_usd("v2_add_liquidity")
                + gas_cost_usd("v2_remove_liquidity")
                + 2 * gas_cost_usd("approve")
            )
        except GasUnitUnmeasured:
            gas_roundtrip = 0.0

        raw: list[dict[str, Any]] = []
        for p in pools:
            try:
                vol = sources.pair_vol_annual(p.symbol, days=30)
            except sources.VolUnavailable:
                vol = None
            # fee APR: prefer the 30-day realised mean (apyBase is an instantaneous
            # annualisation and spikes wildly on small pools); headline is what the
            # naive baseline chases.
            fee_apr = p.apy_mean_30d if p.apy_mean_30d is not None else (
                p.apy_base if p.apy_base is not None else (p.apy or 0.0))
            headline = p.apy if p.apy is not None else (p.apy_base or fee_apr)
            raw.append({
                "pool": p.pool,
                "symbol": p.symbol,
                "underlying_tokens": [t.lower() for t in (p.underlying_tokens or [])],
                "tvl_usd": p.tvl_usd,
                "tvl_14d_ago": sources.tvl_14d_ago(p.pool),
                "fee_apr_pct": float(fee_apr),
                "fee_apr_source": "apyMean30d" if p.apy_mean_30d is not None else "apyBase",
                "emission_apr_pct": float(p.apy_reward or 0.0),
                "headline_apr_pct": float(headline),
                "vol_annual": vol,
            })

        # --- sentry gate on the shortlist (spec §4.2) ---
        depth = _GATE_DEPTH.get(risk, 8)
        prelim = sorted(
            raw,
            key=lambda r: r["fee_apr_pct"] + r["emission_apr_pct"] - (25.0 * (r["vol_annual"] or 0)),
            reverse=True,
        )[:depth]
        gate_tokens: list[str] = []
        for r in prelim:
            for t in r["underlying_tokens"]:
                if t and t not in _ALLOWLIST and t not in gate_tokens:
                    gate_tokens.append(t)
        gate_tokens = gate_tokens[:8]

        sentry: dict[str, dict] = {}
        gate_status = "clean"
        if gate_tokens:
            try:
                from agents.bsc_sentry.agent import gather
                from agents.bsc_sentry.fork import anvil_fork
                from agents.bsc_sentry.scoring import score_report

                with anvil_fork() as w3:
                    for tok in gate_tokens:
                        try:
                            rep = score_report(tok, gather(tok, w3))
                            sentry[tok] = {"verdict": rep.verdict, "score": rep.score,
                                           "hard_fails": rep.hard_fails}
                        except Exception as e:  # noqa: BLE001
                            sentry[tok] = {"verdict": "UNKNOWN", "error": str(e)[:160]}
            except Exception as e:  # noqa: BLE001 - fork unavailable -> gate best-effort
                gate_status = f"unavailable: {str(e)[:160]}"

        # score every candidate now (deterministic given the fetched numbers) so
        # decide() stays pure and the baseline sees identical net-APR figures.
        scored: list[dict[str, Any]] = []
        for r in raw:
            na = net_apr(
                pool=r["pool"], symbol=r["symbol"],
                fee_apr_pct=r["fee_apr_pct"], emission_apr_pct=r["emission_apr_pct"],
                headline_apr_pct=r["headline_apr_pct"], horizon_days=horizon,
                vol_annual=r["vol_annual"], capital_usd=capital,
                gas_usd_roundtrip=gas_roundtrip,
                tvl_now=r["tvl_usd"] or 0.0, tvl_14d_ago=r["tvl_14d_ago"],
            ).as_dict()
            na["tvl_usd"] = r["tvl_usd"]
            na["fee_apr_source"] = r["fee_apr_source"]
            na["underlying_tokens"] = r["underlying_tokens"]
            scored.append(na)

        data = {
            "inputs": {"capital_usd": capital, "horizon_days": horizon, "risk": risk},
            "gas_usd_roundtrip": gas_roundtrip,
            "pools_scored": scored,
            "sentry": sentry,
            "gate_status": gate_status,
            "gated_tokens": gate_tokens,
            # for the top_headline_apr baseline: it picks by `apy` (headline) and
            # reports that pool's realistic `net_apr_pct` — "where the naive pick
            # loses money, show it" (spec §4.3).
            "pools": [{"pool": s["pool"], "symbol": s["symbol"],
                       "apy": s["headline_apr_pct"], "net_apr_pct": s["net_apr_pct"]}
                      for s in scored],
        }
        self._obs_data = data
        return Observation(data=data, snapshot_hash=canonical_hash(data))

    # ---- decide (pure) ----------------------------------------------

    def decide(self, obs: Observation) -> Decision:
        d = obs.data
        sentry = d["sentry"]

        ranked: list[dict] = []
        excluded: list[dict] = []
        for na in d["pools_scored"]:
            na = dict(na)
            toks = na.pop("underlying_tokens", [])
            bad = [t for t in toks if sentry.get(t, {}).get("verdict") == "CRITICAL"]
            if bad:
                na["excluded_reason"] = (
                    f"bsc-sentry flagged {', '.join(bad)} CRITICAL "
                    f"({'; '.join(sentry[bad[0]].get('hard_fails') or ['hard fail'])})"
                )
                excluded.append(na)
            else:
                na["security_screened"] = all(t in _ALLOWLIST or t in sentry for t in toks)
                ranked.append(na)

        ranked.sort(key=lambda x: x["net_apr_pct"], reverse=True)
        eligible = [x for x in ranked if x.get("security_screened")]
        winner = (eligible or ranked or [None])[0]

        return Decision(
            kind="yield_ranking",
            params={
                "winner": winner,
                "ranked": ranked,
                "excluded": excluded,
                "gate_status": d["gate_status"],
                "n_candidates": len(d["pools_scored"]),
            },
            rationale=(
                f"{winner['symbol']} net {winner['net_apr_pct']:.2f}% "
                f"(headline {winner['headline_apr_pct']:.2f}%)"
                if winner else "no eligible pool"
            ),
        )

    # ---- act / report ---------------------------------------------

    def act(self, d: Decision, ctx: ExecContext) -> Actions:
        return Actions()  # Tier 0

    def report(self, d: Decision, a: Actions) -> Result:
        p = d.params
        winner = p["winner"]
        return Result(
            metric=self.manifest.advantage_metric.name,  # net_apr_delta_pct
            unit=self.manifest.advantage_metric.unit,     # pct
            value=float(winner["net_apr_pct"]) if winner else 0.0,
            outputs={
                "winner": winner,
                "ranked": p["ranked"],
                "excluded_by_security_agent": p["excluded"],
                "security_gate_status": p["gate_status"],
                "n_candidates": p["n_candidates"],
                "note": (
                    "net_apr = fee_apr + emission_apr*decay - expected_il - "
                    "amortised_gas - dilution. Source: DefiLlama (PancakeSwap v2 "
                    "BSC) + Binance vol; v3 fee data pending the Envio indexer."
                ),
            },
        )
