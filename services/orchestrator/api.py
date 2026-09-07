"""The orchestrator REST + SSE surface (spec.md §8)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sse_starlette.sse import EventSourceResponse

from . import db, hires, queries, registry
from .schemas import (
    AgentCard,
    AgentDetail,
    CategoryOut,
    HealthReport,
    HireCreated,
    HireStatus,
    ReceiptDetail,
    ReceiptOut,
)

router = APIRouter()


@router.get("/agents", response_model=list[AgentCard])
def list_agents() -> Any:
    return queries.agent_cards()


@router.get("/agents/{agent_id}", response_model=AgentDetail)
def get_agent(agent_id: str) -> Any:
    detail = queries.agent_detail(agent_id)
    if detail is None:
        raise HTTPException(404, f"no agent {agent_id!r}")
    return detail


@router.get("/agents/{agent_id}/receipts", response_model=list[ReceiptOut])
def agent_receipts(agent_id: str, limit: int = Query(25, ge=1, le=200)) -> Any:
    if agent_id not in registry.load_registry():
        raise HTTPException(404, f"no agent {agent_id!r}")
    return queries.receipts_for(agent_id, limit=limit)


@router.get("/categories", response_model=list[CategoryOut])
def list_categories() -> Any:
    return queries.categories()


@router.get("/activity", response_model=list[ReceiptOut])
def activity(limit: int = Query(20, ge=1, le=100)) -> Any:
    return queries.recent_receipts(limit)


# --- hires ---------------------------------------------------------

@router.post("/hires", response_model=HireCreated, status_code=202)
async def create_hire(body: dict) -> Any:
    agent_id = body.get("agent_id")
    tier = body.get("tier")
    inputs = body.get("inputs") or {}
    entry = registry.load_registry().get(agent_id)
    if not entry or not entry.available or entry.manifest is None:
        raise HTTPException(404, f"no agent {agent_id!r}")
    m = entry.manifest
    if tier not in m.tiers:
        raise HTTPException(422, {"tier": f"must be one of {m.tiers}"})
    errors = hires.validate(m, inputs)
    if errors:
        raise HTTPException(422, {"errors": errors})
    hire = await hires.start(agent_id, int(tier), m.apply_defaults(inputs), m)
    return HireCreated(hire_id=hire.id, run_id=hire.run_id, status=hire.status)


@router.get("/hires/{hire_id}", response_model=HireStatus)
def get_hire(hire_id: str) -> Any:
    h = hires.get(hire_id)
    if not h:
        raise HTTPException(404, "unknown hire")
    return h.snapshot()


@router.get("/hires/{hire_id}/stream")
async def stream_hire(hire_id: str) -> Any:
    h = hires.get(hire_id)
    if not h:
        raise HTTPException(404, "unknown hire")

    async def gen():
        async for evt in hires.stream(h):
            yield {"data": json.dumps(evt)}

    return EventSourceResponse(gen())


@router.post("/hires/{hire_id}/cancel")
def cancel_hire(hire_id: str) -> Any:
    if not hires.cancel(hire_id):
        raise HTTPException(409, "hire not cancellable")
    return {"status": "cancelling"}


# --- receipts + report ------------------------------------------

@router.get("/receipts/{receipt_id}", response_model=ReceiptDetail)
def get_receipt(receipt_id: str) -> Any:
    r = queries.receipt_by_id(receipt_id)
    if not r:
        raise HTTPException(404, "unknown receipt")
    from .anchor import proof_for  # local import: contract/anchor lands in T-062

    proof, root = proof_for(receipt_id)
    return ReceiptDetail(
        **r.model_dump(),
        merkle_proof=proof, anchor_root=root,
        verified_hint=("verify: keccak-fold the leaf with the proof and compare to "
                       "anchor_root, then check anchor_root == the BatchAnchored event "
                       "for batch_id on ReceiptAnchor" if root else
                       "not yet anchored — batching runs every 10 min (T-062)"),
    )


@router.get("/report/advantage")
def advantage_report() -> Any:
    from .report import build_advantage_report

    return build_advantage_report()


# --- health -----------------------------------------------------

@router.get("/healthz", response_model=HealthReport)
def healthz() -> Any:
    deps: dict[str, str] = {}
    try:
        with db.session() as s:
            s.execute(text("SELECT 1"))
        deps["db"] = "ok"
    except Exception as e:  # noqa: BLE001
        deps["db"] = f"down: {str(e)[:80]}"
    try:
        from data.cache import _redis

        deps["redis"] = "ok" if _redis() is not None else "down"
    except Exception:  # noqa: BLE001
        deps["redis"] = "down"
    try:
        from data.sources.rpc import block_number

        deps["rpc"] = f"ok (block {block_number()})"
    except Exception as e:  # noqa: BLE001
        deps["rpc"] = f"down: {str(e)[:80]}"
    deps["hummingbot"] = "not_configured (T-041)"
    deps["gateway"] = "not_configured (T-004 profile)"

    status = "ok" if all(v.startswith("ok") for k, v in deps.items()
                         if k in ("db", "rpc")) else "degraded"
    return HealthReport(status=status, deps=deps)
