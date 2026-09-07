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

    # chain
    bsc_rpc_url: str = "https://bsc-rpc.publicnode.com"
    bsc_rpc_url_fallback: str = "https://bsc-dataseed.bnbchain.org"
    bsc_chain_id: int = 56

    # external data
    graph_api_key: str = ""
    bscscan_api_key: str = ""
    binance_base_url: str = "https://api.binance.com"
    defillama_base_url: str = "https://yields.llama.fi"

    @property
    def has_graph_key(self) -> bool:
        return bool(self.graph_api_key.strip())

    @property
    def has_bscscan_key(self) -> bool:
        return bool(self.bscscan_api_key.strip())


@lru_cache
def settings() -> Settings:
    return Settings()
