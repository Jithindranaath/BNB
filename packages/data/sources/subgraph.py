"""PancakeSwap v3 subgraph — pools, poolDayDatas, ticks, positions.

Needs a Graph **query** API key (GRAPH_API_KEY) and a `verified: true` entry in
reference/subgraphs.json. Both are pending (docs/findings/T-003.md): a deploy key
was supplied, not a query key. The client is complete; its live test skips until
the key lands and `scripts/probe/pcs_subgraph.ts` finalises the id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .. import reference
from ..settings import settings
from ._http import post_json

_SUBGRAPH = "pancakeswapV3Bsc"


class SubgraphUnavailable(RuntimeError):
    pass


def _endpoint() -> str:
    s = settings()
    if not s.has_graph_key:
        raise SubgraphUnavailable("GRAPH_API_KEY not set (needs a Graph *query* key)")
    try:
        entry = reference.subgraph(_SUBGRAPH)  # raises until verified: true
    except (KeyError, ValueError) as e:
        raise SubgraphUnavailable(str(e)) from e
    return entry["gateway"].replace("{GRAPH_API_KEY}", s.graph_api_key).replace("{id}", entry["id"])


def query(gql: str, variables: dict | None = None) -> dict:
    body = post_json(_endpoint(), json={"query": gql, "variables": variables or {}})
    if body.get("errors"):
        raise SubgraphUnavailable(f"graphql errors: {body['errors']}")
    return body["data"]


class PoolDayData(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: datetime
    fees_usd: Decimal
    tvl_usd: Decimal
    volume_usd: Decimal


class Pool(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    fee_tier: int
    token0_symbol: str
    token1_symbol: str
    tvl_usd: Decimal


_POOL_FIELDS = """
  id feeTier
  token0 { symbol } token1 { symbol }
  totalValueLockedUSD
"""


def get_pool(pool_address: str) -> Pool:
    data = query(
        f"query($id: ID!) {{ pool(id: $id) {{ {_POOL_FIELDS} }} }}",
        {"id": pool_address.lower()},
    )
    p = data.get("pool")
    if not p:
        raise SubgraphUnavailable(f"pool {pool_address} not found in subgraph")
    return Pool(
        id=p["id"],
        fee_tier=int(p["feeTier"]),
        token0_symbol=p["token0"]["symbol"],
        token1_symbol=p["token1"]["symbol"],
        tvl_usd=Decimal(p["totalValueLockedUSD"]),
    )


def get_pool_day_datas(pool_address: str, days: int = 30) -> list[PoolDayData]:
    data = query(
        """query($pool: String!, $n: Int!) {
          poolDayDatas(first: $n, orderBy: date, orderDirection: desc,
                       where: { pool: $pool }) {
            date feesUSD tvlUSD volumeUSD
          }
        }""",
        {"pool": pool_address.lower(), "n": days},
    )
    rows = data["poolDayDatas"]
    return [
        PoolDayData(
            date=datetime.fromtimestamp(r["date"], tz=UTC),
            fees_usd=Decimal(r["feesUSD"]),
            tvl_usd=Decimal(r["tvlUSD"]),
            volume_usd=Decimal(r["volumeUSD"]),
        )
        for r in rows
    ]
