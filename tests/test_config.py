"""T-070: the deploy-facing bits of orchestrator.config — managed-Postgres URL
schemes and env-driven CORS."""

from __future__ import annotations

from orchestrator.config import OrchestratorSettings


def _s(**kw) -> OrchestratorSettings:
    # _env_file=None so a developer's real .env can't leak into the assertion
    return OrchestratorSettings(_env_file=None, **kw)


def test_managed_postgres_url_schemes_are_normalised():
    neon = _s(database_url="postgres://u:p@ep-x.neon.tech/db?sslmode=require")
    assert neon.database_url == "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require"

    render = _s(database_url="postgresql://u:p@dpg-x/db")
    assert render.database_url == "postgresql+psycopg://u:p@dpg-x/db"

    already = _s(database_url="postgresql+psycopg://u:p@h/db")
    assert already.database_url == "postgresql+psycopg://u:p@h/db"


def test_cors_origins_default_is_permissive_and_env_pins_it():
    assert _s().cors_origins == ["*"]
    pinned = _s(cors_allow_origins="https://a.vercel.app, https://proofstand.xyz")
    assert pinned.cors_origins == ["https://a.vercel.app", "https://proofstand.xyz"]
