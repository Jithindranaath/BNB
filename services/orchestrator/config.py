"""Orchestrator runtime settings.

Local dev reads the repo-root `.env`; a container reads real environment
variables (they win over `.env`, and `.env` is simply absent). See docs/deploy.md.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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

    # Public deploy: comma-separated allowed origins for the browser app. Empty
    # (the default) keeps the permissive "*" the local marketplace dev used — the
    # API is read-only and unauthenticated, so that is safe, but a real domain
    # should pin it. Example: "https://proofstand.vercel.app,https://proofstand.xyz"
    cors_allow_origins: str = ""

    @field_validator("database_url")
    @classmethod
    def _psycopg_scheme(cls, v: str) -> str:
        """Managed Postgres (Neon, Render, Supabase, …) hands out `postgres://`
        or `postgresql://` URLs; SQLAlchemy + psycopg 3 wants `postgresql+psycopg://`.
        Any `?sslmode=require` query is preserved."""
        for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
            if v.startswith(prefix):
                return v
        if v.startswith("postgresql://"):
            return "postgresql+psycopg://" + v[len("postgresql://"):]
        if v.startswith("postgres://"):
            return "postgresql+psycopg://" + v[len("postgres://"):]
        return v

    @property
    def cors_origins(self) -> list[str]:
        items = [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]
        return items or ["*"]


@lru_cache
def config() -> OrchestratorSettings:
    return OrchestratorSettings()
