"""Typed, R1-enforcing access to packages/data/reference/*.json.

Rule R1: addresses/tokens/subgraph ids exist ONLY in the JSON here. Code imports
them through these helpers, which refuse anything not marked `verified: true`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@lru_cache
def _load(name: str) -> dict:
    return json.loads((_DIR / name).read_text())


@lru_cache
def contract(name: str) -> str:
    """Checksummed address of a verified BSC contract, or raise (R1)."""
    entry = _load("addresses.json")["bsc"]["contracts"].get(name)
    if entry is None:
        raise KeyError(f"unknown contract {name!r}; add it to reference/addresses.json (R1)")
    if entry.get("verified") is not True or not entry.get("address"):
        raise ValueError(f"contract {name!r} is not verified — run scripts/verify_reference.ts")
    return entry["address"]


@lru_cache
def token(symbol: str) -> dict:
    """`{address, decimals, ...}` for a verified BSC token, or raise (R1)."""
    entry = _load("tokens.json")["bsc"]["tokens"].get(symbol)
    if entry is None:
        raise KeyError(f"unknown token {symbol!r}; add it to reference/tokens.json (R1)")
    if entry.get("verified") is not True:
        raise ValueError(f"token {symbol!r} is not verified — run scripts/verify_reference.ts")
    return entry


@lru_cache
def token_address(symbol: str) -> str:
    return token(symbol)["address"]


def subgraph(name: str, *, require_verified: bool = True) -> dict:
    """Raw subgraph record. With require_verified (default) raises until T-003
    finalises it against a real Graph query key."""
    entry = _load("subgraphs.json").get(name)
    if entry is None:
        raise KeyError(f"unknown subgraph {name!r}")
    if require_verified and entry.get("verified") is not True:
        raise ValueError(
            f"subgraph {name!r} not verified yet (needs GRAPH_API_KEY; see docs/findings/T-003.md)"
        )
    return entry


@lru_cache
def abi(name: str) -> list:
    """Load reference/abis/<name>.json."""
    return json.loads((_DIR / "abis" / f"{name}.json").read_text())


@lru_cache
def venus_params() -> dict:
    """Venus Core Pool params not exposed by the (Diamond) Comptroller.
    `liquidation_incentive` is verified:false — flagged, not hidden (R6)."""
    return _load("venus_params.json")
