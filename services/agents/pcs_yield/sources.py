"""Data for pcs-yield, from sources that work TODAY (spec.md §4, rule R1/R3):

  - candidate pools + headline / fee / reward APR + TVL history -> DefiLlama
    (`pancakeswap-amm` on BSC; DefiLlama has no PancakeSwap v3 BSC feed yet —
    that arrives when the Envio HyperIndex indexer is live, see docs/envio-indexer.md)
  - price volatility per pair -> Binance klines
  - security gate -> the bsc-sentry agent (see agent.py)

No synthetic fill. A pair with no price history is ranked with IL flagged, not
guessed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from data.calibrate import realized_vol
from data.sources import binance, llama

# BSC LP-token symbol -> Binance base asset. Only pairs whose BOTH legs resolve
# here (or are stable) get an IL estimate.
BINANCE_BASE: dict[str, str] = {
    "WBNB": "BNB", "BNB": "BNB",
    "BTCB": "BTC", "ETH": "ETH", "CAKE": "CAKE",
    "XRP": "XRP", "DOGE": "DOGE", "TRX": "TRX", "ADA": "ADA", "LTC": "LTC",
    "DOT": "DOT", "LINK": "LINK", "MATIC": "MATIC", "AVAX": "AVAX",
    "SOL": "SOL", "UNI": "UNI", "ATOM": "ATOM", "FIL": "FIL",
}
STABLES = {"USDT", "USDC", "BUSD", "DAI", "FDUSD", "TUSD", "USD1"}


class VolUnavailable(RuntimeError):
    pass


def candidate_pools(*, min_tvl_usd: float = 50_000.0, limit: int = 15) -> list[llama.Pool]:
    """PancakeSwap BSC pools by TVL, with both underlying tokens known and a
    headline APR."""
    pools = llama.get_pools(chain="BSC", project="pancakeswap-amm")
    out = [
        p for p in pools
        if (p.tvl_usd or 0) >= min_tvl_usd
        and p.underlying_tokens and len(p.underlying_tokens) == 2
        and (p.apy is not None or p.apy_base is not None)
        and "-" in p.symbol
    ]
    out.sort(key=lambda p: -(p.tvl_usd or 0))
    return out[:limit]


def _legs(symbol: str) -> tuple[str, str]:
    a, b = symbol.upper().split("-", 1)
    return a, b


def _usdt_closes(base: str, days: int) -> pd.DataFrame:
    start_ms = int((datetime.now(tz=UTC) - timedelta(days=days)).timestamp() * 1000)
    kl = binance.get_klines(f"{base}-USDT", "1h", limit=min(1000, days * 24), start_ms=start_ms)
    if not kl:
        raise VolUnavailable(f"no Binance {base}-USDT klines")
    return pd.DataFrame({
        "open_time": [k.open_time for k in kl],
        "close": [float(k.close) for k in kl],
        "high": [float(k.high) for k in kl],
        "low": [float(k.low) for k in kl],
    })


def pair_vol_annual(pool_symbol: str, *, days: int = 30) -> float:
    """Annualised realised vol of price(leg0 / leg1). Stable/stable -> 0.
    Stable/x -> vol of x. x/y -> vol of the x/y ratio series. Raises
    VolUnavailable if a non-stable leg has no Binance market."""
    a, b = _legs(pool_symbol)
    a_stable, b_stable = a in STABLES, b in STABLES
    if a_stable and b_stable:
        return 0.0

    if a_stable ^ b_stable:
        vol_leg = b if a_stable else a
        base = BINANCE_BASE.get(vol_leg)
        if base is None:
            raise VolUnavailable(f"no Binance mapping for {vol_leg}")
        return realized_vol(_usdt_closes(base, days), window_hours=720)

    ba, bb = BINANCE_BASE.get(a), BINANCE_BASE.get(b)
    if ba is None or bb is None:
        raise VolUnavailable(f"no Binance mapping for {a if ba is None else b}")
    da, db = _usdt_closes(ba, days), _usdt_closes(bb, days)
    m = da.merge(db, on="open_time", suffixes=("_a", "_b"))
    if len(m) < 48:
        raise VolUnavailable(f"too few overlapping candles for {a}/{b}")
    ratio = pd.DataFrame({
        "open_time": m["open_time"],
        "close": m["close_a"] / m["close_b"],
        "high": np.maximum(m["high_a"] / m["low_b"], m["close_a"] / m["close_b"]),
        "low": np.minimum(m["low_a"] / m["high_b"], m["close_a"] / m["close_b"]),
    })
    return realized_vol(ratio, window_hours=720)


def tvl_14d_ago(pool_id: str) -> float | None:
    """TVL ~14 days back from DefiLlama's daily chart (earliest point if the
    series is shorter). None if unavailable."""
    try:
        chart = llama.get_pool_chart(pool_id)
    except Exception:  # noqa: BLE001 - dilution term is optional, never fatal
        return None
    pts = [c for c in chart if c.tvl_usd is not None]
    if len(pts) < 2:
        return None
    cutoff = datetime.now(tz=UTC) - timedelta(days=14)
    older = [c for c in pts if c.timestamp <= cutoff]
    return (older[-1] if older else pts[0]).tvl_usd
