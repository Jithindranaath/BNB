"""PancakeSwap v3 subgraph — pools, poolDayDatas, ticks, positions.

PARKED. GRAPH_API_KEY is valid, but The Graph's decentralised network has no
synced PancakeSwap v3 BSC subgraph (both candidate ids are dead — see
docs/findings/T-003.md). `pcs-yield` ships instead on DefiLlama v2 + Binance +
the on-chain sentry gate (T-033). The real v3 fee/day-data source is a
self-hosted Envio HyperIndex indexer (docs/envio-indexer.md); when it is live,
this client is rewritten for the Hasura dialect and pointed at
`settings().pcs_v3_graphql_url`, and a probe is added under scripts/probe/ (R5).
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
