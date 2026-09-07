"""proofstand orchestrator — FastAPI app assembly (spec.md §8).

Run:  uvicorn orchestrator.main:app --reload --port 8080 --app-dir services
"""

from __future__ import annotations

import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import config

log = logging.getLogger("orchestrator")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    from . import queries

    try:
        synced = queries.sync_registry_to_db()
        log.info("registry synced to db: %s", synced)
    except Exception as e:  # noqa: BLE001
        log.warning("registry sync skipped (%s)", e)
    yield


app = FastAPI(title="proofstand orchestrator", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # "*" for local dev; set CORS_ALLOW_ORIGINS to the deployed web origin(s).
    allow_origins=config().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
async def root() -> dict:
    return {"service": "proofstand-orchestrator", "docs": "/docs", "api": "spec.md §8"}
