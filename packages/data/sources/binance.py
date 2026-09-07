"""Binance /api/v3/klines — OHLCV for all calibration + trading baselines.
No auth. 1000 candles/call. Rule R3: real data only, no synthetic series.

Response shape confirmed in scripts/probe/output/binance_klines.json (R5).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from ..settings import settings
from ._http import get_json

_MAX_LIMIT = 1000


class Kline(BaseModel):
    model_config = ConfigDict(frozen=True)

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time: datetime
    quote_volume: Decimal
    trades: int
    taker_buy_base: Decimal
    taker_buy_quote: Decimal

    @classmethod
    def from_row(cls, r: list) -> Kline:
        return cls(
            open_time=datetime.fromtimestamp(r[0] / 1000, tz=UTC),
            open=Decimal(r[1]),
            high=Decimal(r[2]),
            low=Decimal(r[3]),
            close=Decimal(r[4]),
            volume=Decimal(r[5]),
            close_time=datetime.fromtimestamp(r[6] / 1000, tz=UTC),
            quote_volume=Decimal(r[7]),
            trades=int(r[8]),
            taker_buy_base=Decimal(r[9]),
            taker_buy_quote=Decimal(r[10]),
        )


def _symbol(pair: str) -> str:
    """'BNB-USDT' / 'BNBUSDT' / 'bnb_usdt' -> 'BNBUSDT'."""
    return pair.upper().replace("-", "").replace("_", "").replace("/", "")


def get_klines(
    pair: str = "BNB-USDT",
    interval: str = "1h",
    *,
    limit: int = 500,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[Kline]:
    """Fetch up to `limit` klines (paginating past 1000 as needed). When
    start_ms is given, walks forward until `limit` rows or `end_ms` is reached."""
    base = settings().binance_base_url
    sym = _symbol(pair)
    out: list[Kline] = []
    cursor = start_ms

    while len(out) < limit:
        params = {"symbol": sym, "interval": interval, "limit": min(_MAX_LIMIT, limit - len(out))}
        if cursor is not None:
            params["startTime"] = cursor
        if end_ms is not None:
            params["endTime"] = end_ms

        rows = get_json(f"{base}/api/v3/klines", params=params)
        if not rows:
            break
        batch = [Kline.from_row(r) for r in rows]
        out.extend(batch)

        if len(rows) < params["limit"] or start_ms is None:
            break
        cursor = rows[-1][6] + 1  # next ms after last close_time

    return out[:limit]
