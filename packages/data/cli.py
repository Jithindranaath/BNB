"""`python -m data` / `data` console entrypoint (T-011).

    data pull --pair BNB-USDT --days 30 --interval 1h
    data pull --pair BNB-USDT --days 30 --cached      # read cache, no network
    data info --pair BNB-USDT --interval 1h
"""

from __future__ import annotations

import argparse
import sys
import time

from . import cache


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="data", description="proofstand data layer CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pull = sub.add_parser("pull", help="pull historical klines into the local parquet cache")
    pull.add_argument("--pair", default="BNB-USDT")
    pull.add_argument("--days", type=int, default=30)
    pull.add_argument("--interval", default="1h", choices=sorted(cache.INTERVAL_MS))
    pull.add_argument("--cached", action="store_true", help="read cache only, no network")

    info = sub.add_parser("info", help="show what the klines cache holds")
    info.add_argument("--pair", default="BNB-USDT")
    info.add_argument("--interval", default="1h", choices=sorted(cache.INTERVAL_MS))

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "pull":
        t0 = time.monotonic()
        df = cache.read_klines(
            args.pair, args.interval, args.days, refresh=not args.cached
        )
        dt = time.monotonic() - t0
        if df.empty:
            print(f"[data pull] {args.pair} {args.interval}: NO DATA in {dt:.2f}s", file=sys.stderr)
            return 2
        print(
            f"[data pull] {args.pair} {args.interval} {args.days}d: "
            f"{len(df)} candles  {df['open_time'].min().isoformat()} -> "
            f"{df['open_time'].max().isoformat()}  in {dt:.2f}s"
        )
        return 0

    if args.cmd == "info":
        info = cache.klines_cache_info(args.pair, args.interval)
        for k, v in info.items():
            print(f"{k:8} {v}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
