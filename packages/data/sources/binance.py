"""Binance /api/v3/klines — OHLCV for all calibration + trading baselines.
No auth. 1000 candles/call, cache to parquet, refetch only the tail. Impl: T-010.
"""

from __future__ import annotations

RAISE = NotImplementedError("binance source client lands in T-010 (probe first: T-003)")
