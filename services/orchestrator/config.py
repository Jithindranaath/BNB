"""Orchestrator runtime settings, read from the repo-root `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 127.0.0.1, not localhost: on Windows `localhost` can resolve to ::1 first
    # and psycopg's default connect_timeout is infinite -> multi-minute hangs.
    database_url: str = "postgresql+psycopg://proofstand:proofstand@127.0.0.1:5432/proofstand"
    redis_url: str = "redis://127.0.0.1:6379/0"


@lru_cache
def config() -> OrchestratorSettings:
    return OrchestratorSettings()
