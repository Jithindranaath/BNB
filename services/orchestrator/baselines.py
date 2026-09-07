"""Counterfactual runners (architecture.md §9).

Each baseline runs the SAME task on the SAME Observation the agent saw, through a
different (dumb) policy, and returns a `Result` in the agent's declared
metric/unit so the harness can take `agent_value - baseline_value`.

| id                | policy                                             | agent          |
|-------------------|----------------------------------------------------|----------------|
| hodl              | buy the USD notional at t0, hold to t1             | bnb-grid       |
| static_range      | one full-range v3 position at t0, never touched    | pcs-rebalancer |
| top_headline_apr  | pick the highest advertised APR, no risk adjust    | pcs-yield      |
| no_action         | do nothing; replay prices, cost a liquidation      | venus-guard    |
| manual_analyst    | a human's stopwatch time, read from fixtures       | bsc-sentry     |
| zero              | utility: always 0 (used by the _echo test agent)   | _echo          |

`obs.data` is a plain dict the agent's `observe()` built; the exact keys each
baseline needs are in its docstring. Missing data -> BaselineIncomplete (never a
guessed number, R2/R6).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agents.base import Manifest, Observation, Result
from data.calibrate import GasUnitUnmeasured, fee_apr, gas_cost_usd, il_estimate

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class BaselineIncomplete(RuntimeError):
    """The Observation lacks something this baseline needs. Not a soft failure —
    the caller must fix the agent's observe() or supply the fixture."""


def _metric(manifest: Manifest, value: float, **outputs: Any) -> Result:
    m = manifest.advantage_metric
    return Result(metric=m.name, unit=m.unit, value=float(value), outputs=outputs)


def _need(obs: Observation, *keys: str) -> tuple:
    missing = [k for k in keys if k not in obs.data]
    if missing:
        raise BaselineIncomplete(f"Observation missing {missing} for this baseline")
    return tuple(obs.data[k] for k in keys)


def _closes(klines: list[dict]) -> list[float]:
    if not klines:
        raise BaselineIncomplete("empty klines")
    return [float(k["close"]) for k in klines]


# --- baselines ---------------------------------------------------------

def baseline_zero(obs: Observation, manifest: Manifest) -> Result:
    return _metric(manifest, 0.0, policy="zero")


def baseline_hodl(obs: Observation, manifest: Manifest) -> Result:
    """needs obs.data: `klines` (list of {open, close, ...}, chronological),
    `inputs.capital_usd`. Buys `capital_usd` of the base asset at klines[0].open,
    marks to klines[-1].close, minus one entry swap's gas."""
    (klines, inputs) = _need(obs, "klines", "inputs")
    capital = float(inputs["capital_usd"])
    p0 = float(klines[0]["open"])
    p1 = float(klines[-1]["close"])
    qty = capital / p0
    gross = qty * p1 - capital
    try:
        gas = gas_cost_usd("swap_v2")
    except GasUnitUnmeasured as e:  # pragma: no cover - swap_v2 is measured
        raise BaselineIncomplete(str(e)) from e
    return _metric(manifest, gross - gas, entry=p0, exit=p1, gas_usd=gas)


def baseline_static_range(obs: Observation, manifest: Manifest) -> Result:
    """needs obs.data: `pool_day_datas` (for fee APR), `vol_annual`,
    `inputs.capital_usd`, `horizon_days`. Full-range position => fees over the
    horizon minus expected IL. The entry/exit gas term is added when v3 gas units
    are measured (T-042); until then it is flagged, not guessed."""
    (pdd, vol, inputs, horizon) = _need(
        obs, "pool_day_datas", "vol_annual", "inputs", "horizon_days"
    )
    capital = float(inputs["capital_usd"])
    horizon = float(horizon)
    apr = fee_apr(pdd)
    fees = capital * apr * horizon / 365.0
    il = il_estimate(float(vol), horizon, range_width_pct=0.999999)  # ~full range
    il_usd = capital * il
    outputs: dict[str, Any] = {"fee_apr": apr, "fees_usd": fees, "il_usd": il_usd}
    try:
        gas = gas_cost_usd("v3_mint") + gas_cost_usd("v3_burn")
        outputs["gas_usd"] = gas
    except GasUnitUnmeasured:
        gas = 0.0
        outputs["gas_term"] = "UNMEASURED — v3 NPM gas units land in T-042"
    return _metric(manifest, fees - il_usd - gas, **outputs)


def baseline_top_headline_apr(obs: Observation, manifest: Manifest) -> Result:
    """needs obs.data: `pools` (list of dicts with an `apy`/`apr` field, in %).
    Returns the top advertised APR — the agent's net APR minus this is the
    `net_apr_delta_pct`."""
    (pools,) = _need(obs, "pools")
    if not pools:
        raise BaselineIncomplete("no pools to rank")

    def _apr(p: dict) -> float:
        for k in ("apr", "apy", "headline_apr"):
            if p.get(k) is not None:
                return float(p[k])
        raise BaselineIncomplete(f"pool has no apr/apy field: {p}")

    top = max(pools, key=_apr)
    return _metric(manifest, _apr(top), top_pool=top.get("pool") or top.get("symbol"))


def baseline_no_action(obs: Observation, manifest: Manifest) -> Result:
    """needs obs.data: `min_hf` (lowest health factor over the replay window) and
    either `liquidation_loss_usd` (precomputed) or (`debt_usd` + `liq_penalty_pct`).
    If HF never crossed 1, the loss is 0; otherwise it's the penalty paid. Value
    is negative (a loss); the agent's `usd_saved` minus this is the advantage."""
    (min_hf,) = _need(obs, "min_hf")
    if float(min_hf) >= 1.0:
        return _metric(manifest, 0.0, liquidated=False, min_hf=float(min_hf))
    if "liquidation_loss_usd" in obs.data:
        loss = float(obs.data["liquidation_loss_usd"])
    else:
        (debt, pen) = _need(obs, "debt_usd", "liq_penalty_pct")
        loss = float(debt) * float(pen)
    return _metric(manifest, -loss, liquidated=True, min_hf=float(min_hf))


def baseline_manual_analyst(obs: Observation, manifest: Manifest) -> Result:
    """Human-produced, read from fixtures/manual_baselines.json keyed by the
    target address (spec.md §3.5, §9). Never computed."""
    (inputs,) = _need(obs, "inputs")
    target = str(inputs.get("target", "")).lower()
    path = _FIXTURES / "manual_baselines.json"
    if not path.exists():
        raise BaselineIncomplete("fixtures/manual_baselines.json not present")
    table = json.loads(path.read_text())
    row = table.get(target) or table.get(inputs.get("target", ""))
    if not row:
        raise BaselineIncomplete(f"no manual baseline recorded for target {target}")
    metric = manifest.advantage_metric.name
    if metric not in row:
        raise BaselineIncomplete(f"manual baseline for {target} has no {metric!r}")
    return _metric(manifest, float(row[metric]), source="manual_analyst", **row)


_REGISTRY: dict[str, Callable[[Observation, Manifest], Result]] = {
    "hodl": baseline_hodl,
    "static_range": baseline_static_range,
    "top_headline_apr": baseline_top_headline_apr,
    "no_action": baseline_no_action,
    "manual_analyst": baseline_manual_analyst,
    "zero": baseline_zero,
}


def run_baseline(baseline_id: str, obs: Observation, manifest: Manifest) -> Result:
    fn = _REGISTRY.get(baseline_id)
    if fn is None:
        raise KeyError(f"unknown baseline {baseline_id!r}; one of {sorted(_REGISTRY)}")
    return fn(obs, manifest)
