"""FastAPI app. Full route set is spec.md §8; implemented in T-060/T-061.

Run:  uvicorn orchestrator.main:app --reload --port 8080
      (with PYTHONPATH including ./services)
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="proofstand orchestrator", version="0.0.0")


@app.get("/healthz")
async def healthz() -> dict:
    """Per-dependency health. spec.md §8: 'must report each dependency
    individually. During judging you need to know within seconds which leg is
    down.' Wired to real checks in T-060 — until then each leg is 'unknown'."""
    legs = ["db", "redis", "rpc", "hummingbot", "gateway"]
    return {"status": "scaffold", "deps": {leg: "unknown" for leg in legs}}


@app.get("/")
async def root() -> dict:
    return {"service": "proofstand-orchestrator", "see": "spec.md §8 for the API"}
