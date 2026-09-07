"""DefiLlama yields — TVL + APR now and historical. No auth.
Used by pcs-yield for the dilution adjustment (TVL trend) and as an independent
APR cross-check against the PCS subgraph.

Shapes confirmed in scripts/probe/output/defillama_pools.json / _chart.json (R5).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..settings import settings
from ._http import get_json


class Pool(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    pool: str  # DefiLlama pool id (uuid)
    chain: str
    project: str
    symbol: str
    tvl_usd: float | None = Field(default=None, alias="tvlUsd")
    apy: float | None = None
    apy_base: float | None = Field(default=None, alias="apyBase")
    apy_reward: float | None = Field(default=None, alias="apyReward")
    il_7d: float | None = Field(default=None, alias="il7d")
    underlying_tokens: list[str] | None = Field(default=None, alias="underlyingTokens")
    pool_meta: str | None = Field(default=None, alias="poolMeta")


class ChartPoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    timestamp: datetime
    tvl_usd: float | None = Field(default=None, alias="tvlUsd")
    apy: float | None = None
    apy_base: float | None = Field(default=None, alias="apyBase")
    apy_reward: float | None = Field(default=None, alias="apyReward")


def get_pools(*, chain: str | None = None, project: str | None = None) -> list[Pool]:
    body = get_json(f"{settings().defillama_base_url}/pools")
    rows = body["data"]
    pools = [Pool.model_validate(r) for r in rows]
    if chain:
        pools = [p for p in pools if p.chain.lower() == chain.lower()]
    if project:
        pools = [p for p in pools if project.lower() in p.project.lower()]
    return pools


def get_pool_chart(pool_id: str) -> list[ChartPoint]:
    body = get_json(f"{settings().defillama_base_url}/chart/{pool_id}")
    return [ChartPoint.model_validate(r) for r in body["data"]]
