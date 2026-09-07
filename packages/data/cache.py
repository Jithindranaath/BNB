"""Two-tier cache (architecture.md §5).

  Historical time series (klines, poolDayDatas)
      -> parquet on disk, APPEND TAIL ONLY, never refetch history.
  Hot state (subgraph 60s, DefiLlama 300s, live RPC 15s, BscScan 3600s)
      -> redis, with a graceful bypass when redis is down.

Rule R3: everything in here is real data. No synthetic fill.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .settings import settings
from .sources import binance

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent / ".cache"
KLINES_DIR = CACHE_DIR / "klines"

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

# redis TTLs, seconds (architecture.md §5)
TTL = {"subgraph": 60, "defillama": 300, "rpc_live": 15, "bscscan": 3600}


def cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


# --------------------------------------------------------------------------
# hot cache (redis)
# --------------------------------------------------------------------------

_redis_client: Any = None
_redis_down = False


def _redis():
    global _redis_client, _redis_down
    if _redis_down:
        return None
    if _redis_client is None:
        try:
            import redis

            _redis_client = redis.from_url(settings().redis_url, decode_responses=True)
            _redis_client.ping()
        except Exception as e:  # noqa: BLE001
            log.warning("redis unavailable (%s) — hot cache bypassed", e)
            _redis_down = True
            return None
    return _redis_client


def hot_json(key: str, ttl_seconds: int, producer: Callable[[], Any]) -> Any:
    """Return `producer()` result, cached in redis as JSON for `ttl_seconds`.
    If redis is down, just calls `producer()` every time."""
    r = _redis()
    if r is not None:
        try:
            hit = r.get(key)
            if hit is not None:
                return json.loads(hit)
        except Exception as e:  # noqa: BLE001
            log.warning("redis get failed for %s (%s)", key, e)

    value = producer()

    if r is not None:
        try:
            r.setex(key, ttl_seconds, json.dumps(value, default=str))
        except Exception as e:  # noqa: BLE001
            log.warning("redis setex failed for %s (%s)", key, e)
    return value


# --------------------------------------------------------------------------
# parquet time-series cache — klines
# --------------------------------------------------------------------------

_KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote",
]


def _symbol(pair: str) -> str:
    return pair.upper().replace("-", "").replace("_", "").replace("/", "")


def _klines_path(pair: str, interval: str) -> Path:
    return KLINES_DIR / f"{_symbol(pair)}_{interval}.parquet"


def _to_df(klines: list[binance.Kline]) -> pd.DataFrame:
    rows = [
        {
            "open_time": k.open_time,
            "open": float(k.open),
            "high": float(k.high),
            "low": float(k.low),
            "close": float(k.close),
            "volume": float(k.volume),
            "close_time": k.close_time,
            "quote_volume": float(k.quote_volume),
            "trades": int(k.trades),
            "taker_buy_base": float(k.taker_buy_base),
            "taker_buy_quote": float(k.taker_buy_quote),
        }
        for k in klines
    ]
    df = pd.DataFrame(rows, columns=_KLINE_COLS)
    return df


def _merge(existing: pd.DataFrame | None, fresh: pd.DataFrame) -> pd.DataFrame:
    df = fresh if existing is None else pd.concat([existing, fresh], ignore_index=True)
    df = df.drop_duplicates(subset="open_time", keep="last").sort_values("open_time")
    return df.reset_index(drop=True)


def read_klines(
    pair: str = "BNB-USDT",
    interval: str = "1h",
    days: int = 30,
    *,
    refresh: bool = True,
) -> pd.DataFrame:
    """A real OHLCV frame for the last `days` at `interval`.

    Cold: one paginated pull from Binance -> parquet. Warm: reads parquet and
    fetches only the missing tail (candles closed since the last cached one).
    Never refetches history.
    """
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval {interval!r}; one of {sorted(INTERVAL_MS)}")

    step = INTERVAL_MS[interval]
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    want_from_ms = now_ms - days * 86_400_000
    n_target = math.ceil(days * 86_400_000 / step)

    path = _klines_path(pair, interval)
    existing = pd.read_parquet(path) if path.exists() else None

    if not refresh and existing is not None:
        return _window(existing, want_from_ms)

    if existing is None or existing.empty:
        start_ms = want_from_ms
        limit = n_target + 5
    else:
        last_open_ms = int(existing["open_time"].max().timestamp() * 1000)
        start_ms = last_open_ms + step
        limit = max(2, math.ceil((now_ms - start_ms) / step) + 2)

    fresh_rows: list[binance.Kline] = []
    if start_ms < now_ms:
        fresh_rows = binance.get_klines(pair, interval, limit=limit, start_ms=start_ms, end_ms=now_ms)

    if fresh_rows:
        merged = _merge(existing, _to_df(fresh_rows))
        KLINES_DIR.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(path, index=False)
    else:
        merged = existing if existing is not None else _to_df([])

    return _window(merged, want_from_ms)


def _window(df: pd.DataFrame, from_ms: int) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = datetime.fromtimestamp(from_ms / 1000, tz=UTC)
    return df[df["open_time"] >= pd.Timestamp(cutoff)].reset_index(drop=True)


def klines_cache_info(pair: str = "BNB-USDT", interval: str = "1h") -> dict:
    path = _klines_path(pair, interval)
    if not path.exists():
        return {"cached": False, "path": str(path)}
    df = pd.read_parquet(path)
    return {
        "cached": True,
        "path": str(path),
        "rows": len(df),
        "first": df["open_time"].min().isoformat() if len(df) else None,
        "last": df["open_time"].max().isoformat() if len(df) else None,
        "bytes": path.stat().st_size,
    }
