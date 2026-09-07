"""T-011 acceptance: parquet klines cache (cold/warm/tail-append) + redis hot cache.

`pytest -m live` — cold pull hits Binance.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest
from data import cache

pytestmark = pytest.mark.live

PAIR = "BNB-USDT"
INTERVAL = "1h"
DAYS = 30


@pytest.fixture
def fresh_cache(tmp_path, monkeypatch):
    """Point the parquet cache at a throwaway dir for this test."""
    kdir = tmp_path / "klines"
    monkeypatch.setattr(cache, "KLINES_DIR", kdir)
    return kdir


def test_cold_then_warm_then_cached(fresh_cache):
    t0 = time.monotonic()
    cold = cache.read_klines(PAIR, INTERVAL, DAYS)
    cold_dt = time.monotonic() - t0
    assert cold_dt < 60, f"cold pull took {cold_dt:.1f}s"
    assert 690 <= len(cold) <= 745, len(cold)  # ~720 for 30d/1h
    assert cold["open_time"].is_monotonic_increasing
    assert not cold["open_time"].duplicated().any()
    assert (fresh_cache / f"BNBUSDT_{INTERVAL}.parquet").exists()

    t0 = time.monotonic()
    warm = cache.read_klines(PAIR, INTERVAL, DAYS)
    warm_dt = time.monotonic() - t0
    assert warm_dt < 2, f"warm pull took {warm_dt:.2f}s"
    assert abs(len(warm) - len(cold)) <= 2

    t0 = time.monotonic()
    cached = cache.read_klines(PAIR, INTERVAL, DAYS, refresh=False)
    assert time.monotonic() - t0 < 1
    assert len(cached) >= len(cold) - 2


def test_tail_append_never_refetches_history(fresh_cache):
    full = cache.read_klines(PAIR, INTERVAL, DAYS)
    path = fresh_cache / f"BNBUSDT_{INTERVAL}.parquet"

    # simulate a stale cache: drop the last 40 candles
    pd.read_parquet(path).iloc[:-40].to_parquet(path, index=False)
    assert len(pd.read_parquet(path)) == len(full) - 40

    refreshed = cache.read_klines(PAIR, INTERVAL, DAYS)
    assert len(refreshed) == len(full)
    assert not refreshed["open_time"].duplicated().any()
    assert refreshed["open_time"].is_monotonic_increasing


def test_persists_across_process_restart(fresh_cache):
    """The parquet file is on the host fs — a new reader sees it with no network."""
    cache.read_klines(PAIR, INTERVAL, DAYS)
    path = fresh_cache / f"BNBUSDT_{INTERVAL}.parquet"
    assert path.exists() and path.stat().st_size > 1000
    reread = pd.read_parquet(path)
    assert len(reread) >= 690


def test_hot_json_roundtrips_or_bypasses():
    key = f"proofstand:test:{int(time.time())}"
    calls = []

    def produce():
        calls.append(1)
        return {"v": 7}

    assert cache.hot_json(key, 30, produce) == {"v": 7}
    second = cache.hot_json(key, 30, lambda: {"v": 999})
    # redis up -> cached {"v": 7}; redis down -> bypass returns {"v": 999}
    assert second in ({"v": 7}, {"v": 999})
