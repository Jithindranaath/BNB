"""Two-tier cache: parquet on disk (cold) + redis (hot).  Implemented in T-011.

architecture.md §5:
  - klines / poolDayDatas -> parquet, append tail only, never refetch history
  - live state -> redis, per-source TTLs
"""

from __future__ import annotations

from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent / ".cache"


def cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR
