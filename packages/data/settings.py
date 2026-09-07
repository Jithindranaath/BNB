"""Runtime settings for the data layer, read from the repo-root `.env` (rule S3:
keys live in env, loaded once — never in code, logs, or an LLM prompt)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # infra — 127.0.0.1 not localhost (Windows resolves localhost to ::1 first)
    redis_url: str = "redis://127.0.0.1:6379/0"

    # chain
    bsc_rpc_url: str = "https://bsc-rpc.publicnode.com"
    bsc_rpc_url_fallback: str = "https://bsc-dataseed.bnbchain.org"
    # anvil fork source — must serve recent state to unauthenticated clients
    # (PublicNode 403s "archive requests" once head moves past the fork block)
    fork_rpc_url: str = "https://bsc-dataseed1.bnbchain.org"
    bsc_chain_id: int = 56

    # external data
    graph_api_key: str = ""
    bscscan_api_key: str = ""
    binance_base_url: str = "https://api.binance.com"
    defillama_base_url: str = "https://yields.llama.fi"
    # PancakeSwap v3 BSC fee/day data — a self-hosted Envio HyperIndex indexer
    # (docs/envio-indexer.md). Empty until deployed; pcs-yield falls back to
    # DefiLlama v2 + Binance until then.
    envio_api_token: str = ""
    pcs_v3_graphql_url: str = ""

    @property
    def has_graph_key(self) -> bool:
        return bool(self.graph_api_key.strip())

    @property
    def has_bscscan_key(self) -> bool:
        return bool(self.bscscan_api_key.strip())


@lru_cache
def settings() -> Settings:
    return Settings()
