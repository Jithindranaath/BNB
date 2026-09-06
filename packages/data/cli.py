"""`python -m data` entrypoint.

Run from the repo root with the packages dir on the path:

    PYTHONPATH=packages python -m data pull --pair BNB-USDT --days 30

Full implementation lands in T-011 (cache + CLI). For now this parses args and
exits non-zero on any real work, so it can be wired into scripts without
pretending to have data it does not have (rule R2).
"""

from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="data", description="proofstand data layer CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pull = sub.add_parser("pull", help="pull historical data into the local cache")
    pull.add_argument("--pair", default="BNB-USDT", help="e.g. BNB-USDT")
    pull.add_argument("--days", type=int, default=30)
    pull.add_argument("--interval", default="1h")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "pull":
        print(
            f"[data pull] pair={args.pair} days={args.days} interval={args.interval}",
            file=sys.stderr,
        )
        print("NOT IMPLEMENTED: cache + source clients land in T-010/T-011.", file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
